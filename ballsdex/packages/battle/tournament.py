"""
Tournament system for the Battle package.
Admin starts a tournament in a channel → join button for 10 min →
bracket auto-generated → matches run automatically → single elimination until a champion.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

import discord
from tortoise.exceptions import DoesNotExist

from ballsdex.core.models import BallInstance, Player

from .models import Team
from .simulation import build_sim_teams, run_match

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.battle.tournament")

EMBED_COLOR_GOLD = 0xFFD700
EMBED_COLOR_ORANGE = 0xE8501A
EMBED_COLOR_GREEN = 0x2ECC71
EMBED_COLOR_RED = 0xE74C3C
EMBED_COLOR_BLUE = 0x3498DB


def _team_overall(slots: dict) -> float:
    total_off = 0
    total_def = 0
    count = 0
    for pos, inst in slots.items():
        if inst:
            total_off += inst.attack
            total_def += inst.health
            count += 1
    if count == 0:
        return 0.0
    return (total_off + total_def) / (count * 2)


def _team_total_stats(slots: dict) -> tuple[int, int]:
    total_off = sum(inst.attack for inst in slots.values() if inst)
    total_def = sum(inst.health for inst in slots.values() if inst)
    return total_off, total_def


def _win_probability(slots_a: dict, slots_b: dict) -> tuple[float, float]:
    off_a, def_a = _team_total_stats(slots_a)
    off_b, def_b = _team_total_stats(slots_b)

    power_a = off_a * 0.6 + def_a * 0.4
    power_b = off_b * 0.6 + def_b * 0.4

    if power_a + power_b == 0:
        return 50.0, 50.0

    prob_a = (power_a / (power_a + power_b)) * 100
    prob_b = 100 - prob_a
    return round(prob_a, 1), round(prob_b, 1)


def _prob_bar(prob: float, length: int = 10) -> str:
    filled = round(prob / 100 * length)
    empty = length - filled
    return "▓" * filled + "░" * empty


@dataclass
class TournamentPlayer:
    discord_id: int
    display_name: str
    seed: int = 0
    team: Team = None
    slots: dict = field(default_factory=dict)
    eliminated: bool = False
    wins: int = 0


@dataclass
class TournamentMatch:
    round_num: int
    match_num: int
    player_a: Optional[TournamentPlayer] = None
    player_b: Optional[TournamentPlayer] = None
    winner: Optional[TournamentPlayer] = None
    is_bye: bool = False
    score_a: int = 0
    score_b: int = 0


@dataclass
class Tournament:
    channel_id: int
    guild_id: int
    host_id: int
    status: str = "joining"
    players: list[TournamentPlayer] = field(default_factory=list)
    rounds: list[list[TournamentMatch]] = field(default_factory=list)
    current_round: int = 0
    message: Optional[discord.Message] = None
    join_task: Optional[asyncio.Task] = None
    min_players: int = 4
    max_players: int = 32


class TournamentJoinView(discord.ui.View):
    def __init__(self, tournament: Tournament, cog: "TournamentCog"):
        super().__init__(timeout=600)
        self.tournament = tournament
        self.cog = cog

    @discord.ui.button(label="Join", style=discord.ButtonStyle.green, emoji="🏀")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.tournament.status != "joining":
            await interaction.response.send_message(
                "Registration is closed!", ephemeral=True
            )
            return

        uid = interaction.user.id
        if any(p.discord_id == uid for p in self.tournament.players):
            await interaction.response.send_message(
                "You're already registered!", ephemeral=True
            )
            return

        if len(self.tournament.players) >= self.tournament.max_players:
            await interaction.response.send_message(
                f"Tournament is full! ({self.tournament.max_players} max)", ephemeral=True
            )
            return

        player = await Player.get_or_none(discord_id=uid)
        if not player:
            await interaction.response.send_message(
                "You don't have any cards yet!", ephemeral=True
            )
            return

        try:
            team = await Team.get(player=player)
        except DoesNotExist:
            await interaction.response.send_message(
                "You need a lineup first. Use `/team add` or `/team best`.",
                ephemeral=True,
            )
            return

        if not team.is_complete():
            await interaction.response.send_message(
                "Your lineup isn't complete — you need all 5 positions filled.",
                ephemeral=True,
            )
            return

        tp = TournamentPlayer(
            discord_id=uid,
            display_name=interaction.user.display_name,
            team=team,
        )
        self.tournament.players.append(tp)

        await interaction.response.send_message(
            f"✅ You're in! ({len(self.tournament.players)} players registered)",
            ephemeral=True,
        )

        await self.cog._update_join_embed(self.tournament)

        if len(self.tournament.players) >= self.tournament.max_players:
            self.tournament.status = "starting"
            self.stop()

    @discord.ui.button(label="Leave", style=discord.ButtonStyle.grey, emoji="🚪")
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.tournament.status != "joining":
            await interaction.response.send_message(
                "Registration is closed!", ephemeral=True
            )
            return

        uid = interaction.user.id
        before = len(self.tournament.players)
        self.tournament.players = [p for p in self.tournament.players if p.discord_id != uid]

        if len(self.tournament.players) < before:
            await interaction.response.send_message("You've left the tournament.", ephemeral=True)
            await self.cog._update_join_embed(self.tournament)
        else:
            await interaction.response.send_message("You weren't registered.", ephemeral=True)

    async def on_timeout(self):
        if self.tournament.status == "joining":
            self.tournament.status = "starting"
            self.stop()


class TournamentCog:
    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot
        self.active_tournament: Optional[Tournament] = None

    async def start_tournament(
        self,
        interaction: discord.Interaction,
        min_players: int = 4,
        max_players: int = 32,
    ):
        if self.active_tournament and self.active_tournament.status not in ("done", "cancelled"):
            await interaction.followup.send(
                "A tournament is already running! Wait for it to finish or cancel it.",
                ephemeral=True,
            )
            return

        tournament = Tournament(
            channel_id=interaction.channel.id,
            guild_id=interaction.guild.id,
            host_id=interaction.user.id,
            min_players=min_players,
            max_players=max_players,
        )
        self.active_tournament = tournament

        embed = discord.Embed(
            title="🏆  NBAdex Tournament",
            color=EMBED_COLOR_GOLD,
        )
        embed.add_field(
            name="📢 Registration Open",
            value=(
                f"Started by **{interaction.user.display_name}**\n"
                f"Hit the **Join** button below to enter.\n"
                f"You need a full 5-player lineup to compete."
            ),
            inline=False,
        )
        embed.add_field(
            name="⚙️ Settings",
            value=(
                f"```\n"
                f"Format      Single Elimination\n"
                f"Min Players {min_players}\n"
                f"Max Players {max_players}\n"
                f"Reg. Time   10 minutes\n"
                f"```"
            ),
            inline=False,
        )
        embed.add_field(
            name="👥 Players (0)",
            value="*Waiting for players...*",
            inline=False,
        )
        embed.set_footer(text="Registration closes in 10 minutes")

        view = TournamentJoinView(tournament, self)
        msg = await interaction.followup.send(embed=embed, view=view)
        tournament.message = msg

        tournament.join_task = asyncio.create_task(
            self._wait_and_start(tournament, view)
        )

    async def cancel_tournament(self, interaction: discord.Interaction):
        if not self.active_tournament or self.active_tournament.status in ("done", "cancelled"):
            await interaction.followup.send("No active tournament to cancel.", ephemeral=True)
            return

        self.active_tournament.status = "cancelled"
        if self.active_tournament.join_task and not self.active_tournament.join_task.done():
            self.active_tournament.join_task.cancel()

        try:
            channel = self.bot.get_channel(self.active_tournament.channel_id)
            if channel:
                embed = discord.Embed(
                    title="🏆  NBAdex Tournament",
                    description="**Tournament cancelled by admin.**",
                    color=EMBED_COLOR_RED,
                )
                await channel.send(embed=embed)
        except Exception:
            pass

        self.active_tournament = None
        await interaction.followup.send("Tournament cancelled.", ephemeral=True)

    async def _update_join_embed(self, tournament: Tournament):
        if not tournament.message:
            return

        player_lines = []
        for i, p in enumerate(tournament.players, 1):
            player_lines.append(f"`{i}.` {p.display_name}")

        player_text = "\n".join(player_lines) if player_lines else "*Waiting for players...*"
        count = len(tournament.players)

        embed = discord.Embed(
            title="🏆  NBAdex Tournament",
            color=EMBED_COLOR_GOLD,
        )
        embed.add_field(
            name="📢 Registration Open",
            value=(
                f"Hit the **Join** button below to enter.\n"
                f"You need a full 5-player lineup to compete."
            ),
            inline=False,
        )
        embed.add_field(
            name="⚙️ Settings",
            value=(
                f"```\n"
                f"Format      Single Elimination\n"
                f"Min Players {tournament.min_players}\n"
                f"Max Players {tournament.max_players}\n"
                f"```"
            ),
            inline=False,
        )
        embed.add_field(
            name=f"👥 Players ({count})",
            value=player_text,
            inline=False,
        )
        embed.set_footer(text="Registration closes in 10 minutes")

        try:
            await tournament.message.edit(embed=embed)
        except Exception:
            pass

    async def _wait_and_start(self, tournament: Tournament, view: TournamentJoinView):
        await view.wait()

        if tournament.status == "cancelled":
            return

        tournament.status = "starting"

        try:
            await tournament.message.edit(view=None)
        except Exception:
            pass

        channel = self.bot.get_channel(tournament.channel_id)
        if not channel:
            log.error(f"Tournament: channel {tournament.channel_id} not found, aborting.")
            tournament.status = "done"
            self.active_tournament = None
            return

        try:
            if len(tournament.players) < tournament.min_players:
                embed = discord.Embed(
                    title="🏆  NBAdex Tournament",
                    description=(
                        f"**Registration closed** — not enough players.\n"
                        f"Only **{len(tournament.players)}/{tournament.min_players}** joined."
                    ),
                    color=EMBED_COLOR_RED,
                )
                await channel.send(embed=embed)
                return

            await self._load_all_slots(tournament)

            for tp in tournament.players:
                if not tp.eliminated:
                    filled = sum(1 for v in tp.slots.values() if v is not None)
                    if filled < 5:
                        tp.eliminated = True
                        log.info(
                            f"Tournament: disqualified {tp.display_name} "
                            f"(only {filled}/5 valid slots after load)"
                        )

            active = [p for p in tournament.players if not p.eliminated]
            active.sort(key=lambda p: _team_overall(p.slots), reverse=True)
            for i, p in enumerate(active):
                p.seed = i + 1
            tournament.players = active

            self._generate_bracket(tournament)

            await self._show_seedings(tournament, channel)
            await asyncio.sleep(4)
            await self._show_bracket(tournament, channel)
            await asyncio.sleep(3)

            await self._run_tournament(tournament, channel)

        except Exception:
            log.exception("Tournament setup/run failed; cleaning up.")
            try:
                error_embed = discord.Embed(
                    title="⚠️  Tournament Error",
                    description="An unexpected error occurred. The tournament has been cancelled.",
                    color=EMBED_COLOR_RED,
                )
                await channel.send(embed=error_embed)
            except Exception:
                pass
        finally:
            if tournament.status not in ("done", "cancelled"):
                tournament.status = "done"
            self.active_tournament = None

    async def _load_all_slots(self, tournament: Tournament):
        for tp in tournament.players:
            try:
                team = await Team.get(player__discord_id=tp.discord_id)
                slots = {}
                for pos in ("PG", "SG", "SF", "PF", "C"):
                    slot_id = team.get_slot_id(pos)
                    if slot_id:
                        try:
                            inst = await BallInstance.get(pk=slot_id).prefetch_related("ball")
                            slots[pos] = inst
                        except DoesNotExist:
                            slots[pos] = None
                    else:
                        slots[pos] = None
                tp.slots = slots
                tp.team = team
            except DoesNotExist:
                tp.eliminated = True

    async def _show_seedings(self, tournament: Tournament, channel: discord.abc.Messageable):
        embed = discord.Embed(
            title="🏆  NBAdex Tournament — Seedings",
            description=f"**{len(tournament.players)} players** ranked by team power",
            color=EMBED_COLOR_BLUE,
        )

        lines = []
        for p in tournament.players:
            off, defe = _team_total_stats(p.slots)
            ovr = _team_overall(p.slots)
            lines.append(
                f"`{p.seed:>2}.` **{p.display_name}** — "
                f"`{ovr:.0f} OVR` · `{off} OFF` · `{defe} DEF`"
            )

        embed.add_field(
            name="📊 Rankings",
            value="\n".join(lines) if lines else "—",
            inline=False,
        )
        embed.set_footer(text="Higher seed = stronger team on paper")
        await channel.send(embed=embed)

    def _generate_bracket(self, tournament: Tournament):
        active = [p for p in tournament.players if not p.eliminated]
        n = len(active)

        next_pow2 = 1
        while next_pow2 < n:
            next_pow2 *= 2

        num_byes = next_pow2 - n

        top_seeds = active[:num_byes]
        remaining = active[num_byes:]

        round_1 = []
        match_num = 1

        for p in top_seeds:
            m = TournamentMatch(round_num=1, match_num=match_num)
            m.player_a = p
            m.is_bye = True
            m.winner = p
            match_num += 1
            round_1.append(m)

        for i in range(0, len(remaining), 2):
            m = TournamentMatch(round_num=1, match_num=match_num)
            m.player_a = remaining[i]
            if i + 1 < len(remaining):
                m.player_b = remaining[i + 1]
            else:
                m.is_bye = True
                m.winner = m.player_a
            match_num += 1
            round_1.append(m)

        tournament.rounds = [round_1]
        tournament.current_round = 1

    async def _show_bracket(self, tournament: Tournament, channel: discord.abc.Messageable):
        round_name = self._round_name(tournament)

        embed = discord.Embed(
            title=f"🏆  {round_name}",
            color=EMBED_COLOR_ORANGE,
        )

        current_round = tournament.rounds[tournament.current_round - 1]
        lines = []
        for m in current_round:
            if m.winner and m.is_bye:
                lines.append(
                    f"` — ` **{m.winner.display_name}** `[{m.winner.seed}]` ➜ auto-advance"
                )
            elif m.winner:
                a_name = m.player_a.display_name if m.player_a else "?"
                b_name = m.player_b.display_name if m.player_b else "?"
                if m.winner is m.player_a:
                    disp = f"**{a_name}** vs ~~{b_name}~~"
                    score = f"`{m.score_a}-{m.score_b}`"
                else:
                    disp = f"~~{a_name}~~ vs **{b_name}**"
                    score = f"`{m.score_b}-{m.score_a}`"
                lines.append(f"` ✓ ` {disp} → **{m.winner.display_name}** wins {score}")
            else:
                a_name = m.player_a.display_name if m.player_a else "TBD"
                b_name = m.player_b.display_name if m.player_b else "TBD"
                a_seed = f"[{m.player_a.seed}]" if m.player_a else ""
                b_seed = f"[{m.player_b.seed}]" if m.player_b else ""
                lines.append(
                    f"`{m.match_num:>2}.` **{a_name}** `{a_seed}` vs **{b_name}** `{b_seed}`"
                )

        embed.description = "\n".join(lines)

        total_alive = len([p for p in tournament.players if not p.eliminated])
        embed.set_footer(text=f"{total_alive} players remaining")

        await channel.send(embed=embed)

    async def _show_matchup_preview(
        self,
        match: TournamentMatch,
        round_name: str,
        channel: discord.abc.Messageable,
    ):
        pa = match.player_a
        pb = match.player_b

        off_a, def_a = _team_total_stats(pa.slots)
        off_b, def_b = _team_total_stats(pb.slots)
        prob_a, prob_b = _win_probability(pa.slots, pb.slots)

        embed = discord.Embed(
            title=f"⚔️  {round_name} — Game {match.match_num}",
            color=EMBED_COLOR_ORANGE,
        )

        embed.add_field(
            name=f"🟠  {pa.display_name}  `[{pa.seed}]`",
            value=(
                f"```\n"
                f"OFF  {off_a:>5}\n"
                f"DEF  {def_a:>5}\n"
                f"```"
            ),
            inline=True,
        )
        embed.add_field(
            name="VS",
            value="⚡",
            inline=True,
        )
        embed.add_field(
            name=f"🔵  {pb.display_name}  `[{pb.seed}]`",
            value=(
                f"```\n"
                f"OFF  {off_b:>5}\n"
                f"DEF  {def_b:>5}\n"
                f"```"
            ),
            inline=True,
        )

        bar_a = _prob_bar(prob_a, 12)
        bar_b = _prob_bar(prob_b, 12)
        embed.add_field(
            name="📊  Win Probability",
            value=(
                f"**{pa.display_name}**  `{bar_a}` **{prob_a}%**\n"
                f"**{pb.display_name}**  `{bar_b}` **{prob_b}%**"
            ),
            inline=False,
        )

        if prob_a > 65:
            flavor = f"**{pa.display_name}** is the heavy favorite."
        elif prob_b > 65:
            flavor = f"**{pb.display_name}** is the heavy favorite."
        elif abs(prob_a - prob_b) < 10:
            flavor = "This one is a toss-up — could go either way."
        elif prob_a > prob_b:
            flavor = f"**{pa.display_name}** has the edge, but anything can happen."
        else:
            flavor = f"**{pb.display_name}** has the edge, but anything can happen."

        embed.add_field(
            name="💬  Analysis",
            value=flavor,
            inline=False,
        )

        embed.set_footer(text="Game starting in 5 seconds...")
        await channel.send(embed=embed)

    async def _run_tournament(self, tournament: Tournament, channel: discord.abc.Messageable):
        tournament.status = "running"

        while True:
            current_matches = tournament.rounds[tournament.current_round - 1]
            pending = [m for m in current_matches if not m.winner]

            if not pending:
                winners = [m.winner for m in current_matches if m.winner]
                if len(winners) <= 1:
                    break

                next_round = []
                match_num = 1
                for i in range(0, len(winners), 2):
                    m = TournamentMatch(
                        round_num=tournament.current_round + 1,
                        match_num=match_num,
                    )
                    m.player_a = winners[i]
                    if i + 1 < len(winners):
                        m.player_b = winners[i + 1]
                    else:
                        m.is_bye = True
                        m.winner = m.player_a
                    match_num += 1
                    next_round.append(m)

                tournament.rounds.append(next_round)
                tournament.current_round += 1

                round_name = self._round_name(tournament)

                divider = discord.Embed(color=EMBED_COLOR_GOLD)
                divider.description = f"━━━━━━━━━━━━━━━━━━━━\n**{round_name}**\n━━━━━━━━━━━━━━━━━━━━"
                await channel.send(embed=divider)
                await asyncio.sleep(2)

                await self._show_bracket(tournament, channel)
                await asyncio.sleep(3)
                continue

            for match in pending:
                if tournament.status == "cancelled":
                    return

                if match.is_bye:
                    continue

                pa = match.player_a
                pb = match.player_b

                if not pa or not pb:
                    if pa:
                        match.winner = pa
                    elif pb:
                        match.winner = pb
                    continue

                round_name = self._round_name(tournament)
                await self._show_matchup_preview(match, round_name, channel)
                await asyncio.sleep(5)

                try:
                    winner, score_a, score_b = await self._run_single_match(
                        tournament, match, channel
                    )
                    match.winner = winner
                    match.score_a = score_a
                    match.score_b = score_b
                    loser = pb if winner is pa else pa
                    loser.eliminated = True
                    winner.wins += 1

                    remaining = len([p for p in tournament.players if not p.eliminated])

                    w_score = score_a if winner is pa else score_b
                    l_score = score_b if winner is pa else score_a
                    result_embed = discord.Embed(
                        title="✅  Match Result",
                        description=(
                            f"**{winner.display_name}** `[{winner.seed}]` defeats "
                            f"**{loser.display_name}** `[{loser.seed}]` "
                            f"— `{w_score}-{l_score}`"
                        ),
                        color=EMBED_COLOR_GREEN,
                    )
                    result_embed.set_footer(text=f"{remaining} players remaining")
                    await channel.send(embed=result_embed)
                    await asyncio.sleep(4)

                except Exception:
                    log.exception("Tournament match failed")
                    error_embed = discord.Embed(
                        title="⚠️  Match Error",
                        description=(
                            f"Game {match.match_num} encountered an error.\n"
                            f"**{pa.display_name}** advances by default."
                        ),
                        color=EMBED_COLOR_RED,
                    )
                    await channel.send(embed=error_embed)
                    match.winner = pa
                    pb.eliminated = True
                    pa.wins += 1
                    await asyncio.sleep(2)

        final_winners = [m.winner for m in tournament.rounds[-1] if m.winner]
        champion = final_winners[0] if final_winners else None

        tournament.status = "done"
        self.active_tournament = None

        if champion:
            off, defe = _team_total_stats(champion.slots)
            ovr = _team_overall(champion.slots)

            embed = discord.Embed(
                title="👑  CHAMPION",
                color=EMBED_COLOR_GOLD,
            )
            embed.add_field(
                name="🏆  Winner",
                value=f"**{champion.display_name}**",
                inline=True,
            )
            embed.add_field(
                name="📊  Seed",
                value=f"#{champion.seed}",
                inline=True,
            )
            embed.add_field(
                name="🔥  Wins",
                value=f"{champion.wins}",
                inline=True,
            )
            embed.add_field(
                name="📈  Team Stats",
                value=(
                    f"```\n"
                    f"OVR  {ovr:.0f}\n"
                    f"OFF  {off}\n"
                    f"DEF  {defe}\n"
                    f"```"
                ),
                inline=False,
            )

            results_lines = []
            for r_idx, rnd in enumerate(tournament.rounds):
                rname = self._round_name_static(rnd)
                for m in rnd:
                    if m.winner is champion and not m.is_bye:
                        opponent = m.player_b if m.player_a is champion else m.player_a
                        opp_name = opponent.display_name if opponent else "?"
                        if m.player_a is champion:
                            score_str = f"`{m.score_a}-{m.score_b}`"
                        else:
                            score_str = f"`{m.score_b}-{m.score_a}`"
                        results_lines.append(
                            f"vs **{opp_name}** — {score_str}"
                        )
            if results_lines:
                embed.add_field(
                    name="📋  Path to the Title",
                    value="\n".join(results_lines),
                    inline=False,
                )

            embed.add_field(
                name="🏟️  Tournament Info",
                value=(
                    f"Participants: **{len(tournament.players)}**\n"
                    f"Rounds: **{tournament.current_round}**"
                ),
                inline=False,
            )

            await channel.send(embed=embed)
        else:
            await channel.send("Tournament ended with no winner.")

    async def _run_single_match(
        self,
        tournament: Tournament,
        match: TournamentMatch,
        channel: discord.abc.Messageable,
    ) -> tuple[TournamentPlayer, int, int]:
        pa = match.player_a
        pb = match.player_b

        team_a_sim, team_b_sim = build_sim_teams(
            pa.display_name, pa.slots,
            pb.display_name, pb.slots,
        )

        live_embed = discord.Embed(
            title="🏀  TOURNAMENT MATCH",
            description=f"**{pa.display_name}** vs **{pb.display_name}**",
            color=EMBED_COLOR_ORANGE,
        )
        live_msg = await channel.send(embed=live_embed)

        winner_sim = await run_match(
            team_a_sim,
            team_b_sim,
            live_msg,
            "",
            "",
        )

        winner_tp = pa if winner_sim is team_a_sim else pb
        return winner_tp, team_a_sim.score, team_b_sim.score

    def _round_name(self, tournament: Tournament) -> str:
        current_round = tournament.rounds[tournament.current_round - 1]
        return self._round_name_static(current_round)

    @staticmethod
    def _round_name_static(round_matches: list[TournamentMatch]) -> str:
        count = len(round_matches)
        if count == 1:
            return "FINALS"
        elif count == 2:
            return "SEMIFINALS"
        elif count <= 4:
            return "QUARTERFINALS"
        else:
            rnum = round_matches[0].round_num if round_matches else 1
            return f"ROUND {rnum}"
