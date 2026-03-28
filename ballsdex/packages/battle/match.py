"""
/match command group for the Battle package.
Handles match challenges, staking, and simulation launching.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, AsyncIterator, List, Set, cast

import discord
from cachetools import TTLCache
from discord import app_commands
from discord.ext import commands
from tortoise.exceptions import DoesNotExist

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

from .models import PlayerPosition, Team
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
        await interaction.response.defer()

        if len(self.session.locked) >= 2:
            # Both locked — start simulation
            await interaction.channel.send(
                f"🏀 Both players locked in! Starting the match..."
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
        options: List[discord.SelectOption] = []
        async for ball in balls:
            if not ball.tradeable:
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
                    default=ball in self.balls_selected,
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

        if any(ball.pk in stake.ball_ids for ball in self.balls_selected):
            return await interaction.followup.send(
                "You have already added some of the "
                f"{settings.plural_collectible_name} you selected.",
                ephemeral=True,
            )

        if len(self.balls_selected) == 0:
            return await interaction.followup.send(
                f"You have not selected any {settings.plural_collectible_name} "
                "to add to your stake.",
                ephemeral=True,
            )

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

        if failed:
            fail_text = "\n".join(failed)
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
        await self.cog.update_stake_embed(session)

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

@app_commands.guild_only()
class MatchCog(commands.GroupCog, group_name="match"):
    """Challenge other players to a basketball match."""

    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot
        # keyed by (min_user_id, max_user_id)
        self.active_matches: TTLCache[tuple, MatchSession] = TTLCache(
            maxsize=1000, ttl=3600
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id != BATTLE_GUILD_ID:
            await interaction.response.send_message(
                "Battle commands are not available in this server.", ephemeral=True
            )
            return False
        return True

    def _get_session(self, user_id: int) -> MatchSession | None:
        for key, session in self.active_matches.items():
            if session.is_participant(user_id) and session.status not in ("done", "simulating"):
                return session
        return None

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

        # Block both users from being in two matches at once — prevents double-spend exploits
        if self._get_session(interaction.user.id):
            await interaction.followup.send(
                "❌ You're already in an active match. Finish or cancel it before starting a new one.",
                ephemeral=True,
            )
            return
        if self._get_session(member.id):
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
            if not ch_team.is_complete():
                await interaction.followup.send(
                    "❌ Your lineup is not complete. Use `/team add` or `/team best` to fill all 5 positions first.",
                    ephemeral=True,
                )
                return
        except DoesNotExist:
            await interaction.followup.send(
                "❌ You don't have a lineup set. Use `/team add` or `/team best` to build one first.",
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
            if not cd_team.is_complete():
                await interaction.followup.send(
                    f"❌ **{member.display_name}** doesn't have a complete lineup yet.",
                    ephemeral=True,
                )
                return
        except DoesNotExist:
            await interaction.followup.send(
                f"❌ **{member.display_name}** doesn't have a lineup set.",
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

        # ── Card stake
        if card is not None:
            inst = card
            if inst.player_id != player.pk:
                await interaction.followup.send("❌ You don't own that card.", ephemeral=True)
                return
            if inst.pk in stake.ball_ids:
                await interaction.followup.send(
                    f"❌ You already staked **{inst.ball.country}**.", ephemeral=True
                )
                return
            await inst.refresh_from_db()
            if not inst.tradeable:
                await interaction.followup.send(
                    f"❌ **{inst.ball.country}** is not tradeable and cannot be staked.",
                    ephemeral=True,
                )
                return
            if await inst.is_locked():
                await interaction.followup.send(
                    f"❌ **{inst.ball.country}** is locked by another trade or bet.",
                    ephemeral=True,
                )
                return
            stake.ball_ids.append(inst.pk)
            # Lock the card immediately so it can't be traded elsewhere
            await BallInstance.filter(pk=inst.pk).update(tradeable=False)
            msgs.append(f"🎴 **{inst.ball.country}** added to your stakes.")

        # ── Coin stake
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
            # Deduct immediately — returned on cancel, transferred to winner on match end
            money.coins -= coins
            await money.save()
            stake.coins += coins
            msgs.append(f"💰 **{coins:,}** coins added to your stakes and held in escrow.")

        # ── Pack stake
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
            # Deduct immediately — returned on cancel, transferred to winner on match end
            pp.quantity -= pack_amount
            if pp.quantity <= 0:
                await pp.delete()
            else:
                await pp.save()
            stake.packs[pack.pk] = stake.packs.get(pack.pk, 0) + pack_amount
            msgs.append(f"📦 **{pack.name}** ×{pack_amount} added to your stakes and held in escrow.")

        if not msgs:
            await interaction.followup.send(
                "Provide at least one of: `card`, `coins`, `pack`.", ephemeral=True
            )
            return

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
            await interaction.followup.send("You don't have an active match.", ephemeral=True)
            return

        await self.cancel_match(session, cancelled_by=interaction.user.id)
        await interaction.followup.send("✅ Match cancelled. All stakes returned.", ephemeral=True)

    # ─────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────

    async def send_stake_embed(
        self, session: MatchSession, channel: discord.abc.Messageable
    ):
        """Send the stake management embed after the challenge is accepted."""
        guild = self.bot.get_guild(session.guild_id)
        ch_member = guild.get_member(session.challenger_id) if guild else None
        cd_member = guild.get_member(session.challenged_id) if guild else None
        ch_name = ch_member.display_name if ch_member else f"<@{session.challenger_id}>"
        cd_name = cd_member.display_name if cd_member else f"<@{session.challenged_id}>"

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
        ch_member = guild.get_member(session.challenger_id) if guild else None
        cd_member = guild.get_member(session.challenged_id) if guild else None
        ch_name = ch_member.display_name if ch_member else f"<@{session.challenger_id}>"
        cd_name = cd_member.display_name if cd_member else f"<@{session.challenged_id}>"
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

        # Edit the stake message
        if session.message:
            guild = self.bot.get_guild(session.guild_id)
            name = "Unknown"
            if cancelled_by and guild:
                m = guild.get_member(cancelled_by)
                name = m.display_name if m else str(cancelled_by)

            reason_str = {
                "timeout": "⏰ Match expired due to inactivity.",
                "cancelled": f"❌ Match cancelled by **{name}**.",
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
        session.status = "simulating"

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

        # Load teams
        ch_team = await Team.get(player=ch_player)
        cd_team = await Team.get(player=cd_player)

        async def load_slots(team: Team) -> dict:
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
            return slots

        slots_a = await load_slots(ch_team)
        slots_b = await load_slots(cd_team)

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

        winner_player = await Player.get_or_none(discord_id=winner_id)
        loser_player = await Player.get_or_none(discord_id=loser_id)
        winner_stake = session.stakes.get(winner_id, UserStake())
        loser_stake = session.stakes.get(loser_id, UserStake())

        # ── Transfer stakes to winner ─────────────────────────────────
        # Cards
        all_ball_ids = list(winner_stake.ball_ids) + list(loser_stake.ball_ids)
        if all_ball_ids and winner_player:
            await BallInstance.filter(pk__in=all_ball_ids).update(
                player=winner_player, tradeable=True
            )

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

        # Announce winner in channel
        winner_mention = (
            ch_member.mention if winner_id == session.challenger_id and ch_member
            else cd_member.mention if cd_member else f"<@{winner_id}>"
        )
        try:
            await channel.send(
                f"🏆 {winner_mention} wins the match! Congrats!"
            )
        except Exception:
            pass
