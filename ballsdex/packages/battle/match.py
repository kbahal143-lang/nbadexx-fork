"""
/match command group for the Battle package.
Handles match challenges, staking, and simulation launching.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, AsyncIterator, List, Set, cast

import discord
from cachetools import TTLCache
from discord import app_commands
from discord.ext import commands
from tortoise.exceptions import DoesNotExist
from tortoise.expressions import Q

from ballsdex.core.models import Ball, BallInstance, Player
from ballsdex.core.utils.paginator import Pages
from ballsdex.core.utils.sorting import FilteringChoices, SortingChoices, filter_balls, sort_balls
from ballsdex.core.utils.transformers import (
    BallInstanceTransform,
    BallEnabledTransform,
    SpecialEnabledTransform,
)
from ballsdex.settings import settings
from ballsdex.packages.balls.countryballs_paginator import CountryballsSource

from ballsdex.packages.coins.models import Pack, PlayerMoney, PlayerPack
from ballsdex.packages.coins.transformers import PackTransform

from .models import PlayerPosition, Team, MatchResult, BattleProfile, BattleCardStats
from .simulation import build_sim_teams, run_match
from .team import get_or_detect_position, is_base_card

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.battle")

# ──────────────────────────────────────────────────────────
# FILL IN: the Discord server (guild) ID where battle
# commands should be allowed. Matches are blocked everywhere else.
# ──────────────────────────────────────────────────────────
BATTLE_GUILD_ID = 1440962506796433519

# Coin reward given to BOTH winner and loser at the end of every completed match.
MATCH_COIN_REWARD = 20_000
# Maximum number of times a user can collect the match reward in a single UTC day.
# This is also the maximum number of battles allowed per player per day.
MATCH_REWARD_DAILY_LIMIT = 10
# Cooldown in seconds before the same two players can challenge each other again.
CHALLENGE_COOLDOWN_SECS = 600


# ─────────────────────────────────────────────────────────────────────────────
# Session data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class UserStake:
    ball_ids: list[int] = field(default_factory=list)   # BallInstance PKs
    coins:    int = 0
    packs:    dict[int, int] = field(default_factory=dict)  # pack_id -> qty


@dataclass
class MatchSession:
    session_key: tuple[int, int]
    challenger_id: int
    challenged_id: int
    channel_id: int
    guild_id:   int

    message:  discord.Message | None = None
    view:     discord.ui.View | None = None
    status:   str = "pending"   # pending | staking | simulating | done

    stakes:   dict[int, UserStake] = field(default_factory=dict)
    locked:   set[int] = field(default_factory=set)

    def other_player(self, user_id: int) -> int:
        return self.challenged_id if user_id == self.challenger_id else self.challenger_id

    def is_participant(self, user_id: int) -> bool:
        return user_id in (self.challenger_id, self.challenged_id)


# ─────────────────────────────────────────────────────────────────────────────
# Discord Views
# ─────────────────────────────────────────────────────────────────────────────

class MatchAcceptView(discord.ui.View):
    """Sent to the challenged player to accept or decline."""

    def __init__(self, session: MatchSession, cog: "MatchCog"):
        super().__init__(timeout=120)
        self.session = session
        self.cog = cog

    @discord.ui.button(label="Accept ✅", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.session.challenged_id:
            await interaction.response.send_message(
                "This challenge isn't for you!", ephemeral=True
            )
            return
        self.session.status = "staking"
        self.stop()
        await interaction.response.defer()
        await self.cog.send_stake_embed(self.session, interaction.channel)

    @discord.ui.button(label="Decline ❌", style=discord.ButtonStyle.red)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.session.challenged_id:
            await interaction.response.send_message(
                "This challenge isn't for you!", ephemeral=True
            )
            return
        self.session.status = "done"
        self.cog.active_matches.pop(self.session.session_key, None)
        self.stop()
        await interaction.response.edit_message(
            content="❌ Challenge declined.",
            embed=None,
            view=None,
        )

    async def on_timeout(self):
        if self.session.status == "pending":
            self.session.status = "done"
            self.cog.active_matches.pop(self.session.session_key, None)
            try:
                if self.session.message:
                    await self.session.message.edit(
                        content="⏰ Challenge expired — no response.",
                        view=None,
                    )
            except Exception:
                pass


class MatchStakeView(discord.ui.View):
    """Persistent view on the stake embed: Lock In + Cancel."""

    def __init__(self, session: MatchSession, cog: "MatchCog"):
        super().__init__(timeout=1800)
        self.session = session
        self.cog = cog

    @discord.ui.button(label="🔒 Lock In", style=discord.ButtonStyle.green, row=0)
    async def lock_in(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.session.is_participant(interaction.user.id):
            await interaction.response.send_message("Not your match!", ephemeral=True)
            return
        if self.session.status != "staking":
            await interaction.response.send_message(
                "This match is no longer active.", ephemeral=True
            )
            return
        if interaction.user.id in self.session.locked:
            await interaction.response.send_message(
                "You already locked in! Waiting for your opponent.", ephemeral=True
            )
            return

        self.session.locked.add(interaction.user.id)

        # Capture BEFORE any await — only the player who brings locked to exactly 2
        # should start the simulation. Set status synchronously right now so any
        # duplicate button press that arrives after this point sees "simulating"
        # and bails out at the top-of-handler status check.
        i_triggered_start = len(self.session.locked) == 2
        if i_triggered_start:
            self.session.status = "simulating"

        await interaction.response.defer()

        if i_triggered_start:
            # Both locked — start simulation
            await interaction.channel.send(
                "🏀 Both players locked in! Starting the match..."
            )
            asyncio.create_task(self.cog.start_simulation(self.session))
        else:
            await self.cog.update_stake_embed(self.session)
            other_id = self.session.other_player(interaction.user.id)
            try:
                other = interaction.guild.get_member(other_id)
                name = other.display_name if other else "opponent"
            except Exception:
                name = "opponent"
            await interaction.followup.send(
                f"🔒 You've locked in! Waiting for **{name}** to lock in...",
                ephemeral=True,
            )

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.red, row=0)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.session.is_participant(interaction.user.id):
            await interaction.response.send_message("Not your match!", ephemeral=True)
            return
        if self.session.status == "simulating":
            await interaction.response.send_message(
                "⚠️ The match is already being simulated — it can't be cancelled now.",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        await self.cog.cancel_match(self.session, cancelled_by=interaction.user.id)

    async def on_timeout(self):
        if self.session.status == "staking":
            await self.cog.cancel_match(self.session, cancelled_by=None, reason="timeout")


# ─────────────────────────────────────────────────────────────────────────────
# Helper: build stake embed
# ─────────────────────────────────────────────────────────────────────────────

async def _format_stake(guild: discord.Guild, user_id: int, stake: UserStake) -> str:
    lines = []

    if stake.ball_ids:
        names = []
        for bid in stake.ball_ids:
            try:
                inst = await BallInstance.get(pk=bid).prefetch_related("ball")
                names.append(inst.ball.country)
            except DoesNotExist:
                pass
        if names:
            lines.append(f"🎴 {', '.join(names)}")

    if stake.coins:
        lines.append(f"💰 {stake.coins:,} coins")

    for pack_id, qty in stake.packs.items():
        try:
            pack = await Pack.get(pk=pack_id)
            lines.append(f"📦 {pack.name} ×{qty}")
        except DoesNotExist:
            pass

    return "\n".join(lines) if lines else "*Nothing staked yet*"


async def _build_stake_embed(
    session: MatchSession,
    guild: discord.Guild,
    challenger_name: str,
    challenged_name: str,
) -> discord.Embed:
    embed = discord.Embed(
        title="⚔️  Match Challenge",
        description=(
            f"**{challenger_name}** vs **{challenged_name}**\n"
            f"Use `/match stake` to add what you're putting on the line.\n"
            f"Both teams must be complete (5 players) to begin."
        ),
        color=0xE8501A,
    )

    ch_stake = session.stakes.get(session.challenger_id, UserStake())
    cd_stake = session.stakes.get(session.challenged_id, UserStake())

    ch_text = await _format_stake(guild, session.challenger_id, ch_stake)
    cd_text = await _format_stake(guild, session.challenged_id, cd_stake)

    ch_locked = "🔒 LOCKED IN" if session.challenger_id in session.locked else "⏳ Not locked"
    cd_locked = "🔒 LOCKED IN" if session.challenged_id in session.locked else "⏳ Not locked"

    embed.add_field(
        name=f"🟠  {challenger_name}  [{ch_locked}]",
        value=ch_text,
        inline=True,
    )
    embed.add_field(
        name=f"🔵  {challenged_name}  [{cd_locked}]",
        value=cd_text,
        inline=True,
    )
    embed.set_footer(
        text="Lock in when ready — match starts when both players lock in!"
    )
    return embed


# ─────────────────────────────────────────────────────────────────────────────
# Bulk stake view  (mirrors /trade bulk add)
# ─────────────────────────────────────────────────────────────────────────────

class MatchBulkStakeView(Pages):
    """Paginated card picker for bulk staking in a match. Mirrors /trade bulk add exactly."""

    def __init__(
        self,
        interaction: discord.Interaction,
        balls: List[int],
        cog: "MatchCog",
    ):
        self.bot = interaction.client
        self.interaction = interaction
        source = CountryballsSource(balls)
        super().__init__(source, interaction=interaction)
        self.add_item(self.select_ball_menu)
        self.add_item(self.confirm_button)
        self.add_item(self.select_all_button)
        self.add_item(self.clear_button)
        self.balls_selected: Set[BallInstance] = set()
        self.cog = cog

    async def set_options(self, balls: AsyncIterator[BallInstance]):
        # Collect PKs from the cached iterator, then re-fetch with ball prefetched in one
        # query — the CountryballsSource cache stores BallInstance without prefetch_related,
        # so accessing .ball on those objects returns an unresolved QuerySet.
        pks = [b.pk async for b in balls]
        fresh_balls = await BallInstance.filter(pk__in=pks).prefetch_related("ball")
        ball_map = {b.pk: b for b in fresh_balls}

        options: List[discord.SelectOption] = []
        for pk in pks:
            ball = ball_map.get(pk)
            if not ball or not ball.tradeable:
                continue
            emoji = self.bot.get_emoji(int(ball.ball.emoji_id))
            favorite = f"{settings.favorited_collectible_emoji} " if ball.favorite else ""
            special = ball.special_emoji(self.bot, True)
            options.append(
                discord.SelectOption(
                    label=f"{favorite}{special}#{ball.pk:0X} {ball.ball.country}",
                    description=f"ATK: {ball.attack_bonus:+d}% • HP: {ball.health_bonus:+d}% • "
                    f"Caught on {ball.catch_date.strftime('%d/%m/%y %H:%M')}",
                    emoji=emoji,
                    value=f"{ball.pk}",
                    default=False,
                )
            )
        self.select_ball_menu.options = options
        self.select_ball_menu.max_values = len(options)

    @discord.ui.select(min_values=1, max_values=25)
    async def select_ball_menu(
        self, interaction: discord.Interaction, item: discord.ui.Select
    ):
        for value in item.values:
            ball_instance = await BallInstance.get(id=int(value)).prefetch_related(
                "ball", "player"
            )
            self.balls_selected.add(ball_instance)
        await interaction.response.defer()

    @discord.ui.button(label="Select Page", style=discord.ButtonStyle.secondary)
    async def select_all_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer(thinking=True, ephemeral=True)
        for ball in self.select_ball_menu.options:
            ball_instance = await BallInstance.get(id=int(ball.value)).prefetch_related(
                "ball", "player"
            )
            if ball_instance not in self.balls_selected:
                self.balls_selected.add(ball_instance)
        await interaction.followup.send(
            (
                f"All {settings.plural_collectible_name} on this page have been selected.\n"
                "Note that the menu may not reflect this change until you change page."
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.primary)
    async def confirm_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer(thinking=True, ephemeral=True)

        # ── match-specific session check (replaces trade's get_trade) ──
        session = self.cog._get_session(interaction.user.id)
        if not session or session.status != "staking":
            return await interaction.followup.send(
                "The match has been cancelled or is no longer in the staking phase.",
                ephemeral=True,
            )
        if interaction.user.id in session.locked:
            return await interaction.followup.send(
                "You have locked your stake, it cannot be edited! "
                "You can click the cancel button to stop the match instead.",
                ephemeral=True,
            )

        stake = session.stakes[interaction.user.id]

        if len(self.balls_selected) == 0:
            return await interaction.followup.send(
                f"You have not selected any {settings.plural_collectible_name} "
                "to add to your stake.",
                ephemeral=True,
            )

        # Deduplicate by pk — navigating pages can produce two Python objects for the same
        # card (Set uses object identity, not pk equality) which would cause the second
        # copy to appear as a "failed" card even though it was already staked.
        seen_pks: set[int] = set()
        unique_selected: list = []
        for ball in self.balls_selected:
            if ball.pk not in seen_pks:
                seen_pks.add(ball.pk)
                unique_selected.append(ball)
        self.balls_selected = set(unique_selected)

        has_favorite = any(ball.favorite for ball in self.balls_selected)
        if has_favorite:
            from ballsdex.core.utils.buttons import ConfirmChoiceView
            view = ConfirmChoiceView(interaction)
            await interaction.followup.send(
                f"One or more of the {settings.plural_collectible_name} is favorited, "
                "are you sure you want to add it to the match stake?",
                view=view,
                ephemeral=True,
            )
            await view.wait()
            if not view.value:
                return

        failed = []
        for ball in self.balls_selected:
            # Already in this stake (Discord can re-send old pk values when the dropdown
            # remembers previous selections) — skip silently, not a failure.
            if ball.pk in stake.ball_ids:
                continue
            await ball.refresh_from_db()
            if ball.deleted:
                failed.append(f"#{ball.pk:0X} is no longer available")
                continue
            if not ball.tradeable:
                failed.append(f"#{ball.pk:0X} is not tradeable (already locked)")
                continue
            if await ball.is_locked():
                failed.append(f"#{ball.pk:0X} is locked by another trade or bet")
                continue
            await BallInstance.filter(pk=ball.pk).update(tradeable=False)
            stake.ball_ids.append(ball.pk)

        added = len(self.balls_selected) - len(failed)

        # Always refresh the stake embed if at least one card was added
        if added > 0:
            await self.cog.update_stake_embed(session)

        if failed:
            fail_text = "\n".join(failed)
            self.balls_selected.clear()
            return await interaction.followup.send(
                f"Some {settings.plural_collectible_name} could not be added:\n{fail_text}",
                ephemeral=True,
            )

        grammar = (
            f"{settings.collectible_name}"
            if len(self.balls_selected) == 1
            else f"{settings.plural_collectible_name}"
        )
        await interaction.followup.send(
            f"{len(self.balls_selected)} {grammar} added to your stake.", ephemeral=True
        )
        self.balls_selected.clear()

    @discord.ui.button(label="Clear", style=discord.ButtonStyle.danger)
    async def clear_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True, ephemeral=True)
        self.balls_selected.clear()
        await interaction.followup.send(
            f"You have cleared all currently selected {settings.plural_collectible_name}."
            f"This does not affect {settings.plural_collectible_name} within your stake.\n"
            f"There may be an instance where it shows {settings.plural_collectible_name} on the"
            " current page as selected, this is not the case - "
            "changing page will show the correct state.",
            ephemeral=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Match Cog
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# Battle profile stats helper
# ─────────────────────────────────────────────────────────────────────────────

async def _update_battle_stats(
    winner_id: int,
    loser_id: int,
    winner_sim: "TeamSim",
    loser_sim: "TeamSim",
    winner_slots: dict,
    loser_slots: dict,
) -> None:
    """Update BattleProfile win/loss/streak and per-card BattleCardStats after a match."""
    # Winner: +1 win, extend streak
    w_prof, _ = await BattleProfile.get_or_create(discord_id=winner_id)
    w_prof.wins += 1
    w_prof.current_streak = max(w_prof.current_streak, 0) + 1
    await w_prof.save()

    # Loser: +1 loss, reset streak
    l_prof, _ = await BattleProfile.get_or_create(discord_id=loser_id)
    l_prof.losses += 1
    l_prof.current_streak = 0
    await l_prof.save()

    # Per-card points — both teams
    for sim_team, slots, discord_id in (
        (winner_sim, winner_slots, winner_id),
        (loser_sim, loser_slots, loser_id),
    ):
        for pos in ("PG", "SG", "SF", "PF", "C"):
            player_sim = getattr(sim_team, pos.lower(), None)
            inst = slots.get(pos)
            if player_sim is None or inst is None or player_sim.pts <= 0:
                continue
            stat, _ = await BattleCardStats.get_or_create(
                discord_id=discord_id,
                instance_id=inst.pk,
            )
            stat.total_pts += player_sim.pts
            await stat.save()


@app_commands.guild_only()
class MatchCog(commands.GroupCog, group_name="match"):
    """Challenge other players to a basketball match."""

    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot
        # keyed by (min_user_id, max_user_id)
        self.active_matches: TTLCache[tuple, MatchSession] = TTLCache(
            maxsize=1000, ttl=3600
        )
        # Maps session_key -> unix timestamp when the cooldown expires.
        # TTLCache auto-expires entries so the dict never grows unboundedly.
        self._challenge_cooldowns: TTLCache[tuple[int, int], float] = TTLCache(
            maxsize=10_000, ttl=CHALLENGE_COOLDOWN_SECS + 10
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id != BATTLE_GUILD_ID:
            await interaction.response.send_message(
                "Battle commands are not available in this server.", ephemeral=True
            )
            return False
        return True

    def _get_session(self, user_id: int) -> MatchSession | None:
        """Return an active session for a user that is in pending or staking phase."""
        for key, session in self.active_matches.items():
            if session.is_participant(user_id) and session.status not in ("done", "simulating"):
                return session
        return None

    def _is_in_any_active_match(self, user_id: int) -> bool:
        """True if user is in any match that hasn't finished yet (includes simulating)."""
        for session in self.active_matches.values():
            if session.is_participant(user_id) and session.status != "done":
                return True
        return False

    def _session_key(self, a: int, b: int) -> tuple[int, int]:
        return (min(a, b), max(a, b))

    # ─────────────────────────────────────────────────────────────────
    # /match begin
    # ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="begin")
    @app_commands.describe(member="The player you want to challenge")
    async def match_begin(self, interaction: discord.Interaction, member: discord.Member):
        """Challenge another player to a basketball match."""
        await interaction.response.defer()

        if member.id == interaction.user.id:
            await interaction.followup.send("You can't challenge yourself!", ephemeral=True)
            return
        if member.bot:
            await interaction.followup.send("You can't challenge a bot!", ephemeral=True)
            return

        key = self._session_key(interaction.user.id, member.id)

        if key in self.active_matches:
            await interaction.followup.send(
                "There's already an active match between you two! "
                "Use `/match cancel` to cancel it first.",
                ephemeral=True,
            )
            return

        # 3-minute cooldown between the same pair after a match ends or is cancelled
        cooldown_remaining = self._challenge_cooldowns.get(key, 0) - time.time()
        if cooldown_remaining > 0:
            mins = int(cooldown_remaining // 60)
            secs = int(cooldown_remaining % 60)
            wait_str = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"
            await interaction.followup.send(
                f"❌ You two recently played. Please wait **{wait_str}** before challenging again.",
                ephemeral=True,
            )
            return

        # Block both users from being in two matches at once — includes simulating matches
        if self._is_in_any_active_match(interaction.user.id):
            await interaction.followup.send(
                "❌ You're already in an active match. Finish it before starting a new one.",
                ephemeral=True,
            )
            return
        if self._is_in_any_active_match(member.id):
            await interaction.followup.send(
                f"❌ **{member.display_name}** is already in an active match and can't be challenged right now.",
                ephemeral=True,
            )
            return

        # Check challenger has a complete team
        ch_player = await Player.get_or_none(discord_id=interaction.user.id)
        if not ch_player:
            await interaction.followup.send(
                "You don't have any cards yet!", ephemeral=True
            )
            return

        try:
            ch_team = await Team.get(player=ch_player)
        except DoesNotExist:
            await interaction.followup.send(
                "❌ You don't have a lineup set. Use `/team add` or `/team best` to build one first.",
                ephemeral=True,
            )
            return
        if not ch_team.is_complete():
            await interaction.followup.send(
                "❌ Your lineup isn't full yet. You need all 5 positions filled "
                "(PG, SG, SF, PF, C) before you can challenge someone.",
                ephemeral=True,
            )
            return

        # Check challenged has a complete team
        cd_player = await Player.get_or_none(discord_id=member.id)
        if not cd_player:
            await interaction.followup.send(
                f"**{member.display_name}** doesn't have any cards yet!", ephemeral=True
            )
            return

        try:
            cd_team = await Team.get(player=cd_player)
        except DoesNotExist:
            await interaction.followup.send(
                f"❌ **{member.display_name}** doesn't have a lineup set.",
                ephemeral=True,
            )
            return
        if not cd_team.is_complete():
            await interaction.followup.send(
                f"❌ **{member.display_name}**'s lineup isn't full. "
                "They need all 5 positions filled before they can be challenged.",
                ephemeral=True,
            )
            return

        # ── Daily battle limit — block the match entirely if either player maxed out ──
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        ch_today = await MatchResult.filter(
            Q(challenger_discord_id=interaction.user.id) | Q(challenged_discord_id=interaction.user.id),
            played_at__gte=today_start,
        ).count()
        cd_today = await MatchResult.filter(
            Q(challenger_discord_id=member.id) | Q(challenged_discord_id=member.id),
            played_at__gte=today_start,
        ).count()

        if ch_today >= MATCH_REWARD_DAILY_LIMIT:
            await interaction.followup.send(
                f"❌ You've played **{ch_today}/{MATCH_REWARD_DAILY_LIMIT}** battles today — daily limit reached. Come back tomorrow!",
                ephemeral=True,
            )
            return
        if cd_today >= MATCH_REWARD_DAILY_LIMIT:
            await interaction.followup.send(
                f"❌ **{member.display_name}** has played **{cd_today}/{MATCH_REWARD_DAILY_LIMIT}** battles today — daily limit reached.",
                ephemeral=True,
            )
            return

        # ── Stats difference check — block if teams are more than 200 total stats apart ──
        async def _team_total_stats(team: Team) -> int:
            total = 0
            for _pos in ("PG", "SG", "SF", "PF", "C"):
                _sid = team.get_slot_id(_pos)
                if _sid:
                    try:
                        _inst = await BallInstance.get(pk=_sid).prefetch_related("ball")
                        total += _inst.battle_attack + _inst.battle_health
                    except Exception:
                        pass
            return total

        ch_stats = await _team_total_stats(ch_team)
        cd_stats = await _team_total_stats(cd_team)
        stats_diff = abs(ch_stats - cd_stats)
        if stats_diff > 300:
            await interaction.followup.send(
                f"❌ The stat gap between your teams is too large (**{stats_diff}** point difference, max **300**).\n"
                f"Your team: **{ch_stats}** total stats · {member.display_name}'s team: **{cd_stats}** total stats.",
                ephemeral=True,
            )
            return

        # Create session
        session = MatchSession(
            session_key=key,
            challenger_id=interaction.user.id,
            challenged_id=member.id,
            channel_id=interaction.channel.id,
            guild_id=interaction.guild.id,
            stakes={
                interaction.user.id: UserStake(),
                member.id: UserStake(),
            },
        )
        self.active_matches[key] = session

        # Send challenge embed
        embed = discord.Embed(
            title="🏀  Match Challenge!",
            description=(
                f"{member.mention}, **{interaction.user.display_name}** has challenged you to a battle!\n\n"
                f"Both lineups are complete. Accept to set stakes and begin!"
            ),
            color=0xE8501A,
        )
        view = MatchAcceptView(session, self)
        msg = await interaction.followup.send(embed=embed, view=view)
        session.message = msg

    # ─────────────────────────────────────────────────────────────────
    # /match stake
    # ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="stake")
    @app_commands.describe(
        card="A card to stake (optional)",
        coins="Amount of coins to stake (optional)",
        pack="A pack to stake (optional)",
        pack_amount="How many of that pack to stake (default: 1)",
    )
    async def match_stake(
        self,
        interaction: discord.Interaction,
        card:        BallInstanceTransform | None = None,
        coins:       int | None = None,
        pack:        PackTransform | None = None,
        pack_amount: int = 1,
    ):
        """Add items to your match stakes."""
        await interaction.response.defer(ephemeral=True)

        session = self._get_session(interaction.user.id)
        if not session or session.status != "staking":
            await interaction.followup.send(
                "You don't have an active match in the staking phase.\n"
                "Use `/match begin @player` to challenge someone first.",
                ephemeral=True,
            )
            return

        if interaction.user.id in session.locked:
            await interaction.followup.send(
                "You've already locked in! You can't change stakes after locking in.",
                ephemeral=True,
            )
            return

        player = await Player.get_or_none(discord_id=interaction.user.id)
        if not player:
            await interaction.followup.send("Something went wrong finding your account.", ephemeral=True)
            return

        stake = session.stakes[interaction.user.id]
        msgs: list[str] = []

        # ── Validate everything FIRST before any DB mutations ────────────────
        # This prevents partial-write bugs where e.g. coins are deducted but a
        # later pack check fails, leaving coins silently in escrow.

        card_inst = None
        if card is not None:
            card_inst = await BallInstance.get(pk=card.pk).prefetch_related("ball")
            if card_inst.player_id != player.pk:
                await interaction.followup.send("❌ You don't own that card.", ephemeral=True)
                return
            if card_inst.pk in stake.ball_ids:
                await interaction.followup.send(
                    f"❌ You already staked **{card_inst.ball.country}**.", ephemeral=True
                )
                return
            await card_inst.refresh_from_db()
            if not card_inst.tradeable:
                await interaction.followup.send(
                    f"❌ **{card_inst.ball.country}** is not tradeable and cannot be staked.",
                    ephemeral=True,
                )
                return
            if await card_inst.is_locked():
                await interaction.followup.send(
                    f"❌ **{card_inst.ball.country}** is locked by another trade or bet.",
                    ephemeral=True,
                )
                return

        money = None
        if coins is not None:
            if coins <= 0:
                await interaction.followup.send("❌ Coins must be positive.", ephemeral=True)
                return
            money, _ = await PlayerMoney.get_or_create(player=player)
            if money.coins < coins:
                await interaction.followup.send(
                    f"❌ Not enough coins. You have **{money.coins:,}** coins.",
                    ephemeral=True,
                )
                return

        pp = None
        if pack is not None:
            if pack_amount <= 0:
                await interaction.followup.send("❌ Pack amount must be at least 1.", ephemeral=True)
                return
            pp = await PlayerPack.get_or_none(player=player, pack=pack)
            owned_qty = pp.quantity if pp else 0
            if owned_qty < pack_amount:
                already_staked = stake.packs.get(pack.pk, 0)
                await interaction.followup.send(
                    f"❌ You only have **{owned_qty}** of that pack available"
                    + (f" (**{already_staked}** already in escrow)." if already_staked else "."),
                    ephemeral=True,
                )
                return

        if card_inst is None and coins is None and pack is None:
            await interaction.followup.send(
                "Provide at least one of: `card`, `coins`, `pack`.", ephemeral=True
            )
            return

        # ── All checks passed — apply mutations atomically ───────────────────

        if card_inst is not None:
            stake.ball_ids.append(card_inst.pk)
            await BallInstance.filter(pk=card_inst.pk).update(tradeable=False)
            msgs.append(f"🎴 **{card_inst.ball.country}** added to your stakes.")

        if coins is not None:
            money.coins -= coins
            await money.save()
            stake.coins += coins
            msgs.append(f"💰 **{coins:,}** coins added to your stakes and held in escrow.")

        if pack is not None:
            if pp is not None:
                pp.quantity -= pack_amount
                if pp.quantity <= 0:
                    await pp.delete()
                else:
                    await pp.save()
            stake.packs[pack.pk] = stake.packs.get(pack.pk, 0) + pack_amount
            msgs.append(f"📦 **{pack.name}** ×{pack_amount} added to your stakes and held in escrow.")

        await self.update_stake_embed(session)
        await interaction.followup.send("\n".join(msgs), ephemeral=True)

    # ─────────────────────────────────────────────────────────────────
    # /match bulk
    # ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="bulk")
    @app_commands.describe(
        countryball="The countryball you would like to filter the results to",
        sort="Choose how countryballs are sorted. Can be used to show duplicates.",
        special="Filter the results to a special event",
        filter="Filter the results to a specific filter",
    )
    async def match_bulk(
        self,
        interaction: discord.Interaction,
        countryball: BallEnabledTransform | None = None,
        sort: SortingChoices | None = None,
        special: SpecialEnabledTransform | None = None,
        filter: FilteringChoices | None = None,
    ):
        """
        Bulk add countryballs to the ongoing match stake, with parameters to aid with searching.

        Parameters
        ----------
        countryball: Ball
            The countryball you would like to filter the results to
        sort: SortingChoices
            Choose how countryballs are sorted. Can be used to show duplicates.
        special: Special
            Filter the results to a special event
        filter: FilteringChoices
            Filter the results to a specific filter
        """
        await interaction.response.defer(ephemeral=True, thinking=True)

        session = self._get_session(interaction.user.id)
        if not session or session.status != "staking":
            await interaction.followup.send(
                "No active match in staking phase.", ephemeral=True
            )
            return
        if interaction.user.id in session.locked:
            await interaction.followup.send(
                "You have locked your stake, it cannot be edited! "
                "You can click the cancel button to stop the match instead.",
                ephemeral=True,
            )
            return

        query = BallInstance.filter(
            player__discord_id=interaction.user.id,
            tradeable=True,
            ball__tradeable=True,
        )
        if countryball:
            query = query.filter(ball=countryball)
        if special:
            query = query.filter(special=special)
        if sort:
            query = sort_balls(sort, query)
        if filter:
            query = filter_balls(filter, query, interaction.guild_id)

        balls = cast(list[int], await query.values_list("id", flat=True))
        if not balls:
            await interaction.followup.send(
                f"No {settings.plural_collectible_name} found.", ephemeral=True
            )
            return

        view = MatchBulkStakeView(interaction, balls, self)
        await view.start(
            content=f"Select the {settings.plural_collectible_name} you want to add "
            "to your stake, note that the display will wipe on pagination however "
            f"the selected {settings.plural_collectible_name} will remain."
        )

    # ─────────────────────────────────────────────────────────────────
    # /match remove
    # ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="remove")
    @app_commands.describe(card="The card to remove from your stakes")
    async def match_remove(
        self,
        interaction: discord.Interaction,
        card: BallInstanceTransform,
    ):
        """Remove a card from your match stakes."""
        await interaction.response.defer(ephemeral=True)

        session = self._get_session(interaction.user.id)
        if not session or session.status != "staking":
            await interaction.followup.send("No active match in staking phase.", ephemeral=True)
            return

        if interaction.user.id in session.locked:
            await interaction.followup.send("You've already locked in!", ephemeral=True)
            return

        stake = session.stakes[interaction.user.id]
        card = await BallInstance.get(pk=card.pk).prefetch_related("ball")
        if card.pk not in stake.ball_ids:
            await interaction.followup.send(
                f"❌ **{card.ball.country}** is not in your stakes.", ephemeral=True
            )
            return

        stake.ball_ids.remove(card.pk)
        await BallInstance.filter(pk=card.pk).update(tradeable=True)
        await self.update_stake_embed(session)
        await interaction.followup.send(
            f"✅ **{card.ball.country}** removed from your stakes.", ephemeral=True
        )

    # ─────────────────────────────────────────────────────────────────
    # /match cancel
    # ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="cancel")
    async def match_cancel(self, interaction: discord.Interaction):
        """Cancel your current match."""
        await interaction.response.defer(ephemeral=True)

        session = self._get_session(interaction.user.id)
        if not session:
            # Check if they're in a simulating match — give a clearer message
            for s in self.active_matches.values():
                if s.is_participant(interaction.user.id) and s.status == "simulating":
                    await interaction.followup.send(
                        "⚠️ Your match is currently being simulated — it can't be cancelled now.",
                        ephemeral=True,
                    )
                    return
            await interaction.followup.send("You don't have an active match.", ephemeral=True)
            return

        await self.cancel_match(session, cancelled_by=interaction.user.id)
        await interaction.followup.send("✅ Match cancelled. All stakes returned.", ephemeral=True)

    # ─────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────

    async def _resolve_member_name(
        self, guild: discord.Guild | None, user_id: int
    ) -> str:
        """Return display name for a user — falls back to API fetch if not in cache."""
        if guild is None:
            return f"<@{user_id}>"
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except Exception:
                pass
        return member.display_name if member else f"<@{user_id}>"

    async def send_stake_embed(
        self, session: MatchSession, channel: discord.abc.Messageable
    ):
        """Send the stake management embed after the challenge is accepted."""
        guild = self.bot.get_guild(session.guild_id)
        ch_name = await self._resolve_member_name(guild, session.challenger_id)
        cd_name = await self._resolve_member_name(guild, session.challenged_id)

        embed = await _build_stake_embed(session, guild, ch_name, cd_name)
        view = MatchStakeView(session, self)
        session.view = view
        msg = await channel.send(embed=embed, view=view)
        session.message = msg

    async def update_stake_embed(self, session: MatchSession):
        """Refresh the stake embed in place."""
        if not session.message:
            return
        guild = self.bot.get_guild(session.guild_id)
        ch_name = await self._resolve_member_name(guild, session.challenger_id)
        cd_name = await self._resolve_member_name(guild, session.challenged_id)
        embed = await _build_stake_embed(session, guild, ch_name, cd_name)
        try:
            await session.message.edit(embed=embed, view=session.view)
        except Exception:
            pass

    async def cancel_match(
        self,
        session: MatchSession,
        cancelled_by: int | None,
        reason: str = "cancelled",
    ):
        """Cancel a match and return all locked cards, coins, and packs."""
        if session.status in ("simulating", "done"):
            return

        session.status = "done"
        self.active_matches.pop(session.session_key, None)

        # Unlock all staked cards
        all_ball_ids: list[int] = []
        for stake in session.stakes.values():
            all_ball_ids.extend(stake.ball_ids)

        if all_ball_ids:
            await BallInstance.filter(pk__in=all_ball_ids).update(tradeable=True)

        # Return coins and packs to each player
        for uid, stake in session.stakes.items():
            p = await Player.get_or_none(discord_id=uid)
            if not p:
                continue
            if stake.coins > 0:
                pm, _ = await PlayerMoney.get_or_create(player=p)
                pm.coins += stake.coins
                await pm.save()
            for pack_id, qty in stake.packs.items():
                if qty <= 0:
                    continue
                pp, _ = await PlayerPack.get_or_create(player=p, pack_id=pack_id)
                pp.quantity += qty
                await pp.save()

        # Set 3-minute cooldown so same pair can't instantly re-challenge
        self._challenge_cooldowns[session.session_key] = time.time() + CHALLENGE_COOLDOWN_SECS

        # Edit the stake message
        if session.message:
            guild = self.bot.get_guild(session.guild_id)
            name = "Unknown"
            if cancelled_by and guild:
                m = guild.get_member(cancelled_by)
                if m is None:
                    # Member not in local cache — fetch from Discord API
                    try:
                        m = await guild.fetch_member(cancelled_by)
                    except Exception:
                        pass
                name = m.display_name if m else f"<@{cancelled_by}>"

            reason_str = {
                "timeout":   "⏰ Match expired due to inactivity.",
                "cancelled": f"❌ Match cancelled by **{name}**.",
                "error":     "⚠️ Match cancelled due to an internal error. All stakes have been returned.",
            }.get(reason, f"❌ Match cancelled by **{name}**.")

            try:
                await session.message.edit(
                    content=reason_str,
                    embed=None,
                    view=None,
                )
            except Exception:
                pass

    async def start_simulation(self, session: MatchSession):
        """Run the match simulation — called after both players lock in."""
        # Guard: bail only if already finished. Status is already "simulating"
        # (set synchronously in lock_in before this task was created) so we
        # must NOT check for "simulating" here or we'd bail immediately.
        if session.status == "done":
            return

        try:
            await self._run_simulation(session)
        except Exception:
            log.exception("Unhandled crash in start_simulation — forcing session cleanup")
            # Only clean up if the inner body didn't already mark it done
            if session.status != "done":
                session.status = "done"
                self.active_matches.pop(session.session_key, None)
                all_ids: list[int] = []
                for _s in session.stakes.values():
                    all_ids.extend(_s.ball_ids)
                if all_ids:
                    try:
                        await BallInstance.filter(pk__in=all_ids).update(tradeable=True)
                    except Exception:
                        pass
                for _uid, _s in session.stakes.items():
                    _p = await Player.get_or_none(discord_id=_uid)
                    if not _p:
                        continue
                    if _s.coins > 0:
                        _pm, _ = await PlayerMoney.get_or_create(player=_p)
                        _pm.coins += _s.coins
                        await _pm.save()
                    for _pack_id, _qty in _s.packs.items():
                        if _qty > 0:
                            _pp, _ = await PlayerPack.get_or_create(player=_p, pack_id=_pack_id)
                            _pp.quantity += _qty
                            await _pp.save()
                try:
                    _ch = self.bot.get_channel(session.channel_id)
                    if _ch:
                        await _ch.send(
                            "⚠️ The match crashed unexpectedly — all stakes returned. "
                            "You can now start a new match."
                        )
                except Exception:
                    pass

    async def _run_simulation(self, session: MatchSession):
        """Inner simulation body — always called via start_simulation, never directly."""
        guild = self.bot.get_guild(session.guild_id)
        ch_member = guild.get_member(session.challenger_id) if guild else None
        cd_member = guild.get_member(session.challenged_id) if guild else None
        # Members may not be in the cache — fetch from API if needed
        if guild:
            if ch_member is None:
                try:
                    ch_member = await guild.fetch_member(session.challenger_id)
                except Exception:
                    pass
            if cd_member is None:
                try:
                    cd_member = await guild.fetch_member(session.challenged_id)
                except Exception:
                    pass
        ch_name = ch_member.display_name if ch_member else f"<@{session.challenger_id}>"
        cd_name = cd_member.display_name if cd_member else f"<@{session.challenged_id}>"

        ch_player = await Player.get_or_none(discord_id=session.challenger_id)
        cd_player = await Player.get_or_none(discord_id=session.challenged_id)

        # Guard: both players must have a DB record
        if not ch_player or not cd_player:
            missing_name = ch_name if not ch_player else cd_name
            session.status = "staking"
            await self.cancel_match(session, cancelled_by=None, reason="cancelled")
            try:
                channel = self.bot.get_channel(session.channel_id)
                if channel:
                    await channel.send(
                        f"❌ Match cancelled — **{missing_name}** has no account on record. "
                        "All stakes returned."
                    )
            except Exception:
                pass
            return

        # Load teams — guard against team being deleted between challenge and simulation
        try:
            ch_team = await Team.get(player=ch_player)
        except DoesNotExist:
            session.status = "staking"
            await self.cancel_match(session, cancelled_by=None, reason="cancelled")
            try:
                channel = self.bot.get_channel(session.channel_id)
                if channel:
                    await channel.send(
                        f"❌ Match cancelled — **{ch_name}**'s lineup no longer exists. "
                        "All stakes returned."
                    )
            except Exception:
                pass
            return
        try:
            cd_team = await Team.get(player=cd_player)
        except DoesNotExist:
            session.status = "staking"
            await self.cancel_match(session, cancelled_by=None, reason="cancelled")
            try:
                channel = self.bot.get_channel(session.channel_id)
                if channel:
                    await channel.send(
                        f"❌ Match cancelled — **{cd_name}**'s lineup no longer exists. "
                        "All stakes returned."
                    )
            except Exception:
                pass
            return

        async def load_slots(team: Team) -> dict:
            slots = {}
            for pos in ("PG", "SG", "SF", "PF", "C"):
                slot_id = team.get_slot_id(pos)
                if slot_id:
                    try:
                        inst = await BallInstance.get(pk=slot_id).prefetch_related("ball", "special")
                        slots[pos] = inst
                    except DoesNotExist:
                        slots[pos] = None
                else:
                    slots[pos] = None
            return slots

        slots_a = await load_slots(ch_team)
        slots_b = await load_slots(cd_team)

        missing_a = [pos for pos in ("PG", "SG", "SF", "PF", "C") if not slots_a.get(pos)]
        missing_b = [pos for pos in ("PG", "SG", "SF", "PF", "C") if not slots_b.get(pos)]
        if missing_a or missing_b:
            session.status = "staking"
            await self.cancel_match(session, cancelled_by=None, reason="cancelled")
            try:
                channel = self.bot.get_channel(session.channel_id)
                if channel:
                    parts = []
                    if missing_a:
                        parts.append(f"{ch_name} is missing positions: {', '.join(missing_a)}")
                    if missing_b:
                        parts.append(f"{cd_name} is missing positions: {', '.join(missing_b)}")
                    await channel.send(
                        "❌ Match cancelled — one or both lineups are incomplete:\n"
                        + "\n".join(parts)
                    )
            except Exception:
                pass
            return

        # ── Verify card ownership hasn't changed since staking
        # (a card that was traded away during staking should not play for this team)
        def ownership_errors(slots: dict, player_pk: int, owner_name: str) -> list[str]:
            errs = []
            for pos, inst in slots.items():
                if inst and inst.player_id != player_pk:
                    errs.append(f"{owner_name}'s **{pos}** card is no longer owned by them")
            return errs

        ownership_errs = (
            ownership_errors(slots_a, ch_player.pk, ch_name)
            + ownership_errors(slots_b, cd_player.pk, cd_name)
        )
        if ownership_errs:
            session.status = "staking"
            await self.cancel_match(session, cancelled_by=None, reason="cancelled")
            try:
                channel = self.bot.get_channel(session.channel_id)
                if channel:
                    for err in ownership_errs:
                        await channel.send(
                            f"❌ {err} — match cancelled, all stakes returned."
                        )
            except Exception:
                pass
            return

        team_a_sim, team_b_sim = build_sim_teams(ch_name, slots_a, cd_name, slots_b)

        # Format stake text for final embed
        ch_stake = session.stakes.get(session.challenger_id, UserStake())
        cd_stake = session.stakes.get(session.challenged_id, UserStake())

        ch_stake_text = await _format_stake(guild, session.challenger_id, ch_stake)
        cd_stake_text = await _format_stake(guild, session.challenged_id, cd_stake)

        # Edit stake message to show simulation starting
        if session.message:
            try:
                sim_embed = discord.Embed(
                    title="🏀  Match Starting!",
                    description=f"**{ch_name}** vs **{cd_name}**\nSimulation beginning...",
                    color=0xFF4500,
                )
                await session.message.edit(embed=sim_embed, view=None)
            except Exception:
                pass

        # Get the channel for the live match embed
        try:
            channel = self.bot.get_channel(session.channel_id)
            if not channel:
                channel = await self.bot.fetch_channel(session.channel_id)

            live_embed = discord.Embed(
                title="🏀  MATCH STARTING",
                description=f"**{ch_name}** vs **{cd_name}**\nGet ready...",
                color=0xE8501A,
            )
            live_msg = await channel.send(embed=live_embed)
        except Exception as e:
            log.exception("Failed to send live match message")
            # cancel_match guards against "simulating" status — reset it first so stakes are returned
            session.status = "staking"
            await self.cancel_match(session, cancelled_by=None, reason="error")
            return

        # Run the simulation
        try:
            winner_sim = await run_match(
                team_a_sim,
                team_b_sim,
                live_msg,
                ch_stake_text,
                cd_stake_text,
            )
        except Exception:
            log.exception("Match simulation failed — returning all stakes")
            session.status = "done"
            self.active_matches.pop(session.session_key, None)
            # Return cards
            all_ids: list[int] = list(ch_stake.ball_ids) + list(cd_stake.ball_ids)
            if all_ids:
                await BallInstance.filter(pk__in=all_ids).update(tradeable=True)
            # Return coins and packs to each original staker
            for uid, stake_obj in session.stakes.items():
                p = await Player.get_or_none(discord_id=uid)
                if not p:
                    continue
                if stake_obj.coins > 0:
                    pm, _ = await PlayerMoney.get_or_create(player=p)
                    pm.coins += stake_obj.coins
                    await pm.save()
                for pack_id, qty in stake_obj.packs.items():
                    if qty > 0:
                        pp, _ = await PlayerPack.get_or_create(player=p, pack_id=pack_id)
                        pp.quantity += qty
                        await pp.save()
            return

        # Determine winner and loser user IDs by object identity (not name string — avoids
        # false result if both players happen to share the same display name)
        winner_id = session.challenger_id if winner_sim is team_a_sim else session.challenged_id
        loser_id = session.challenged_id if winner_id == session.challenger_id else session.challenger_id
        loser_sim = team_b_sim if winner_sim is team_a_sim else team_a_sim

        winner_player = await Player.get_or_none(discord_id=winner_id)
        loser_player = await Player.get_or_none(discord_id=loser_id)

        # ── Daily reward tracking — count BEFORE saving so current match isn't double-counted
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        winner_today = await MatchResult.filter(
            Q(challenger_discord_id=winner_id) | Q(challenged_discord_id=winner_id),
            played_at__gte=today_start,
        ).count()
        loser_today = await MatchResult.filter(
            Q(challenger_discord_id=loser_id) | Q(challenged_discord_id=loser_id),
            played_at__gte=today_start,
        ).count()

        # ── Save match result to DB
        try:
            await MatchResult.create(
                challenger_discord_id=session.challenger_id,
                challenged_discord_id=session.challenged_id,
                winner_discord_id=winner_id,
                winner_score=winner_sim.score,
                loser_score=loser_sim.score,
            )
        except Exception:
            log.exception("Failed to save MatchResult")

        # ── Update battle profiles and per-card stats
        winner_slots = slots_a if winner_sim is team_a_sim else slots_b
        loser_slots = slots_b if winner_sim is team_a_sim else slots_a
        try:
            await _update_battle_stats(
                winner_id, loser_id,
                winner_sim, loser_sim,
                winner_slots, loser_slots,
            )
        except Exception:
            log.exception("Failed to update battle profiles")

        # ── Set 3-minute challenge cooldown for this pair
        self._challenge_cooldowns[session.session_key] = time.time() + CHALLENGE_COOLDOWN_SECS
        winner_stake = session.stakes.get(winner_id, UserStake())
        loser_stake = session.stakes.get(loser_id, UserStake())

        # ── Transfer stakes to winner ─────────────────────────────────
        # Separate: loser's cards are the ones the winner actually "won"
        winner_ball_ids = list(winner_stake.ball_ids)
        loser_ball_ids  = list(loser_stake.ball_ids)
        all_ball_ids    = winner_ball_ids + loser_ball_ids

        if all_ball_ids and winner_player:
            await BallInstance.filter(pk__in=all_ball_ids).update(
                player=winner_player, tradeable=True
            )
            # Mark loser's cards as traded — sets trade history on each card
            if loser_ball_ids and loser_player:
                await BallInstance.filter(pk__in=loser_ball_ids).update(
                    trade_player=loser_player
                )
            # Transfer BattleCardStats for loser's staked cards to the winner.
            # Winner's own staked cards stay under winner_id (no change needed).
            if loser_ball_ids and loser_player:
                await BattleCardStats.filter(
                    discord_id=loser_id,
                    instance_id__in=loser_ball_ids,
                ).update(discord_id=winner_id)
        elif all_ball_ids:
            await BallInstance.filter(pk__in=all_ball_ids).update(tradeable=True)

        # Coins (already deducted from both players at stake time — give pooled total to winner)
        total_coins = winner_stake.coins + loser_stake.coins
        if total_coins > 0 and winner_player:
            w_money, _ = await PlayerMoney.get_or_create(player=winner_player)
            w_money.coins += total_coins
            await w_money.save()

        # Packs (already deducted from both players at stake time — give all to winner)
        if winner_player:
            for stake_obj in session.stakes.values():
                for pack_id, qty in stake_obj.packs.items():
                    if qty <= 0:
                        continue
                    pp_dst, _ = await PlayerPack.get_or_create(
                        player=winner_player, pack_id=pack_id
                    )
                    pp_dst.quantity += qty
                    await pp_dst.save()

        session.status = "done"
        self.active_matches.pop(session.session_key, None)

        # ── Give 50k flat match reward to both players (each capped at 10/day independently)
        # Anti-exploit: reward only on COMPLETED matches, each user tracked separately,
        # limit resets at UTC midnight, and the 3-minute cooldown prevents rapid farming.
        winner_reward_given = False
        loser_reward_given = False

        if winner_today < MATCH_REWARD_DAILY_LIMIT and winner_player:
            try:
                wm, _ = await PlayerMoney.get_or_create(player=winner_player)
                wm.coins += MATCH_COIN_REWARD
                await wm.save()
                winner_reward_given = True
            except Exception:
                log.exception("Failed to give match reward to winner")

        if loser_today < MATCH_REWARD_DAILY_LIMIT and loser_player:
            try:
                lm, _ = await PlayerMoney.get_or_create(player=loser_player)
                lm.coins += MATCH_COIN_REWARD
                await lm.save()
                loser_reward_given = True
            except Exception:
                log.exception("Failed to give match reward to loser")

        # ── Build win announcement embed ──────────────────────────────
        winner_mention = (
            ch_member.mention if winner_id == session.challenger_id and ch_member
            else cd_member.mention if cd_member else f"<@{winner_id}>"
        )

        # Fetch names + IDs of the loser's cards (what the winner received)
        won_lines: list[str] = []
        for bid in loser_ball_ids:
            try:
                inst = await BallInstance.get(pk=bid).prefetch_related("ball")
                won_lines.append(f"**{inst.ball.country}** `#{inst.pk:0X}`")
            except Exception:
                won_lines.append(f"`#{bid:0X}`")

        win_embed = discord.Embed(
            title="🏆  Match Result",
            description=f"{winner_mention} wins the match! Congrats!",
            color=0xFFD700,
        )
        if won_lines:
            win_embed.add_field(
                name="📦  Cards received",
                value="\n".join(won_lines),
                inline=False,
            )
        if total_coins > 0:
            win_embed.add_field(
                name="🪙  Coins received",
                value=f"{total_coins:,} coins",
                inline=False,
            )

        # Packs received — combine all stakes (winner's returned + loser's won)
        all_packs: dict[int, int] = {}
        for stake_obj in session.stakes.values():
            for pack_id, qty in stake_obj.packs.items():
                if qty > 0:
                    all_packs[pack_id] = all_packs.get(pack_id, 0) + qty
        if all_packs:
            pack_lines: list[str] = []
            for pack_id, qty in all_packs.items():
                try:
                    pack = await Pack.get(id=pack_id)
                    pack_lines.append(f"**{pack.name}** x{qty}")
                except Exception:
                    pack_lines.append(f"Pack #{pack_id} x{qty}")
            win_embed.add_field(
                name="🎁  Packs received",
                value="\n".join(pack_lines),
                inline=False,
            )

        # ── Match completion reward — 50k to both players (if under daily limit)
        reward_lines: list[str] = []
        if winner_reward_given:
            used_after = winner_today + 1
            reward_lines.append(
                f"🏆 **{winner_sim.owner}** +{MATCH_COIN_REWARD:,} coins "
                f"({used_after}/{MATCH_REWARD_DAILY_LIMIT} today)"
            )
        elif winner_today >= MATCH_REWARD_DAILY_LIMIT:
            reward_lines.append(
                f"🏆 **{winner_sim.owner}** — daily reward limit reached "
                f"({MATCH_REWARD_DAILY_LIMIT}/{MATCH_REWARD_DAILY_LIMIT} today)"
            )
        if loser_reward_given:
            used_after = loser_today + 1
            reward_lines.append(
                f"❌ **{loser_sim.owner}** +{MATCH_COIN_REWARD:,} coins "
                f"({used_after}/{MATCH_REWARD_DAILY_LIMIT} today)"
            )
        elif loser_today >= MATCH_REWARD_DAILY_LIMIT:
            reward_lines.append(
                f"❌ **{loser_sim.owner}** — daily reward limit reached "
                f"({MATCH_REWARD_DAILY_LIMIT}/{MATCH_REWARD_DAILY_LIMIT} today)"
            )
        if reward_lines:
            win_embed.add_field(
                name="🪙  Match Completion Rewards",
                value="\n".join(reward_lines),
                inline=False,
            )

        try:
            await channel.send(embed=win_embed)
        except Exception:
            pass
