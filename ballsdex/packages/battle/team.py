"""
/team command group for the Battle package.
All commands work with enabled base player cards only.
"""

import logging
import re
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands
from tortoise.exceptions import DoesNotExist

from ballsdex.core.models import Ball, BallInstance, Player
from ballsdex.core.utils.transformers import BallInstanceTransform
from ballsdex.settings import settings

from .models import PlayerPosition, Team
from .positions import POSITION_LABELS, get_position_for_name

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.battle")

# ──────────────────────────────────────────────────────────
# FILL IN: the Discord server (guild) ID where battle
# commands should be allowed. Teams are blocked everywhere else.
# ──────────────────────────────────────────────────────────
BATTLE_GUILD_ID = 1440962506796433519

# Only letters, spaces, apostrophes, hyphens, and dots — no numbers, no parentheses
_BASE_CARD_RE = re.compile(r"^[A-Za-z'\-\.\s]+$")

POSITION_CHOICES = [
    app_commands.Choice(name="Point Guard (PG)", value="PG"),
    app_commands.Choice(name="Shooting Guard (SG)", value="SG"),
    app_commands.Choice(name="Small Forward (SF)", value="SF"),
    app_commands.Choice(name="Power Forward (PF)", value="PF"),
    app_commands.Choice(name="Center (C)", value="C"),
]


def is_base_card(ball: Ball) -> bool:
    """Returns True if this is a simple, enabled player-name card."""
    if not ball.enabled:
        return False
    return bool(_BASE_CARD_RE.match(ball.country))


async def get_or_detect_position(ball: Ball) -> PlayerPosition | None:
    """
    Return the PlayerPosition for this ball.
    Auto-creates from NBA_POSITIONS dict if not already in DB.
    """
    try:
        return await PlayerPosition.get(ball_id=ball.pk)
    except DoesNotExist:
        pass

    name = ball.country
    pos = get_position_for_name(name)
    if pos is not None:
        primary, secondary = pos
        return await PlayerPosition.create(ball_id=ball.pk, primary=primary, secondary=secondary)

    return None


def _score_instance(inst: BallInstance, position: str) -> float:
    """Compute a position-weighted score for auto-assignment."""
    pos_weights = {
        "PG": (0.60, 0.40),  # (offense_weight, defense_weight)
        "SG": (0.60, 0.40),
        "SF": (0.50, 0.50),
        "PF": (0.40, 0.60),
        "C":  (0.35, 0.65),
    }
    ow, dw = pos_weights.get(position, (0.5, 0.5))
    return inst.ball.rarity * 200 + inst.attack * ow + inst.health * dw


@app_commands.guild_only()
class TeamCog(commands.GroupCog, group_name="team"):
    """Manage your basketball lineup."""

    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id != BATTLE_GUILD_ID:
            await interaction.response.send_message(
                "Battle commands are not available in this server.", ephemeral=True
            )
            return False
        return True

    # ─────────────────────────────────────────────────────────────────
    # /team add
    # ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="add")
    @app_commands.describe(
        card="The player card to add to your lineup",
        position="Position to assign this player",
    )
    @app_commands.choices(position=POSITION_CHOICES)
    async def team_add(
        self,
        interaction: discord.Interaction,
        card: BallInstanceTransform,
        position: app_commands.Choice[str],
    ):
        """Add a player card to your lineup at a specific position."""
        await interaction.response.defer(ephemeral=True)

        inst = card
        ball = inst.ball
        pos = position.value

        # 1. Must be an enabled base card
        if not is_base_card(ball):
            await interaction.followup.send(
                f"❌ **{ball.country}** is not a base player card.\n"
                "Only enabled cards with simple player names (no years, no special tags) can be in your lineup.",
                ephemeral=True,
            )
            return

        # 2. Must belong to the user
        player = await Player.get_or_none(discord_id=interaction.user.id)
        if not player or inst.player_id != player.pk:
            await interaction.followup.send("❌ You don't own that card.", ephemeral=True)
            return

        # 3. Must have a known position
        pp = await get_or_detect_position(ball)
        if pp is None:
            await interaction.followup.send(
                f"❌ **{ball.country}** doesn't have a known basketball position yet.\n"
                "Ask an admin to assign one via the admin panel.",
                ephemeral=True,
            )
            return

        # 4. Position must be allowed
        if not pp.allows(pos):
            allowed = pp.display()
            await interaction.followup.send(
                f"❌ **{ball.country}** plays **{allowed}**, not **{pos}**.\n"
                f"You can only place them at their correct position(s).",
                ephemeral=True,
            )
            return

        # 5. Card must not already be on this team (same slot or any other slot)
        team, _ = await Team.get_or_create(player=player)
        for check_pos in ("PG", "SG", "SF", "PF", "C"):
            existing_id = team.get_slot_id(check_pos)
            if not existing_id:
                continue
            if existing_id == inst.pk:
                await interaction.followup.send(
                    f"❌ **{ball.country}** is already in your **{check_pos}** slot.",
                    ephemeral=True,
                )
                return
            # Also block same player type (e.g. two Jokic cards)
            try:
                existing_inst = await BallInstance.get(pk=existing_id).prefetch_related("ball")
                if existing_inst.ball.pk == ball.pk:
                    await interaction.followup.send(
                        f"❌ **{ball.country}** is already in your **{check_pos}** slot. "
                        "A player can only appear once in your lineup.",
                        ephemeral=True,
                    )
                    return
            except Exception:
                pass

        # Assign
        team.set_slot_id(pos, inst.pk)
        await team.save()

        star = "⭐" * max(1, round(ball.rarity * 5))
        await interaction.followup.send(
            f"✅ **{ball.country}** [{pp.display()}] added to your **{POSITION_LABELS[pos]}** slot!\n"
            f"{star}  ⚔ {inst.attack}  🛡 {inst.health}",
            ephemeral=True,
        )

    # ─────────────────────────────────────────────────────────────────
    # /team remove
    # ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="remove")
    @app_commands.describe(position="Which position slot to clear")
    @app_commands.choices(position=POSITION_CHOICES)
    async def team_remove(
        self,
        interaction: discord.Interaction,
        position: app_commands.Choice[str],
    ):
        """Remove a player from a specific position slot."""
        await interaction.response.defer(ephemeral=True)
        player = await Player.get_or_none(discord_id=interaction.user.id)
        if not player:
            await interaction.followup.send("You don't have a team yet.", ephemeral=True)
            return

        try:
            team = await Team.get(player=player)
        except DoesNotExist:
            await interaction.followup.send("You don't have a team yet.", ephemeral=True)
            return

        pos = position.value
        if not team.get_slot_id(pos):
            await interaction.followup.send(
                f"The **{POSITION_LABELS[pos]}** slot is already empty.", ephemeral=True
            )
            return

        team.set_slot_id(pos, None)
        await team.save()
        await interaction.followup.send(
            f"✅ Cleared your **{POSITION_LABELS[pos]}** slot.", ephemeral=True
        )

    # ─────────────────────────────────────────────────────────────────
    # /team clear
    # ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="clear")
    async def team_clear(self, interaction: discord.Interaction):
        """Clear your entire lineup."""
        await interaction.response.defer(ephemeral=True)
        player = await Player.get_or_none(discord_id=interaction.user.id)
        if not player:
            await interaction.followup.send("You don't have a team yet.", ephemeral=True)
            return

        try:
            team = await Team.get(player=player)
        except DoesNotExist:
            await interaction.followup.send("You don't have a team yet.", ephemeral=True)
            return

        for pos in ("PG", "SG", "SF", "PF", "C"):
            team.set_slot_id(pos, None)
        await team.save()
        await interaction.followup.send("🗑️ Your lineup has been cleared.", ephemeral=True)

    # ─────────────────────────────────────────────────────────────────
    # /team best
    # ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="best")
    async def team_best(self, interaction: discord.Interaction):
        """Automatically fill your lineup with your best cards at each position."""
        await interaction.response.defer(ephemeral=True)
        player = await Player.get_or_none(discord_id=interaction.user.id)
        if not player:
            await interaction.followup.send("You don't have any cards yet.", ephemeral=True)
            return

        # Fetch all owned enabled BallInstances
        all_insts = (
            await BallInstance.filter(player=player)
            .prefetch_related("ball")
        )

        # Filter to base cards only
        base_insts = [i for i in all_insts if is_base_card(i.ball)]
        if not base_insts:
            await interaction.followup.send(
                "You don't have any eligible base player cards.", ephemeral=True
            )
            return

        # Fetch/detect positions for all base cards
        # Build: {inst_pk: PlayerPosition}
        pos_map: dict[int, PlayerPosition] = {}
        for inst in base_insts:
            pp = await get_or_detect_position(inst.ball)
            if pp:
                pos_map[inst.pk] = pp

        # Greedy assignment: for each position pick the highest-scoring available card
        # that plays there (primary preferred over secondary).
        # Both the card instance AND the player type (ball) must be unassigned
        # so the same player can never appear at two positions.
        team, _ = await Team.get_or_create(player=player)
        assigned: set[int] = set()       # BallInstance PKs already assigned
        assigned_balls: set[int] = set() # Ball (player type) PKs already assigned
        result_lines: list[str] = []

        for pos in ("PG", "SG", "SF", "PF", "C"):
            # Primary-position candidates first, then secondary
            primary_cands = [
                i for i in base_insts
                if i.pk in pos_map
                and pos_map[i.pk].primary == pos
                and i.pk not in assigned
                and i.ball.pk not in assigned_balls
            ]
            secondary_cands = [
                i for i in base_insts
                if i.pk in pos_map
                and pos_map[i.pk].secondary == pos
                and i.pk not in assigned
                and i.ball.pk not in assigned_balls
            ]

            candidates = primary_cands or secondary_cands
            if not candidates:
                team.set_slot_id(pos, None)
                result_lines.append(f"**{pos}** — No eligible card found")
                continue

            best = max(candidates, key=lambda i: _score_instance(i, pos))
            team.set_slot_id(pos, best.pk)
            assigned.add(best.pk)
            assigned_balls.add(best.ball.pk)
            result_lines.append(
                f"**{pos}** — {best.ball.country}  ⚔ {best.attack}  🛡 {best.health}"
            )

        await team.save()
        summary = "\n".join(result_lines)
        await interaction.followup.send(
            f"🤖 **Auto-lineup set!**\n{summary}\n\nUse `/team info` to see your full lineup.",
            ephemeral=True,
        )

    # ─────────────────────────────────────────────────────────────────
    # /team info  (quick stats — no image)
    # ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="info")
    @app_commands.describe(member="View another player's lineup info (optional)")
    async def team_info(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
    ):
        """Show a quick stats breakdown of a lineup."""
        await interaction.response.defer(ephemeral=True)

        target = member or interaction.user
        player = await Player.get_or_none(discord_id=target.id)
        if not player:
            await interaction.followup.send("No cards found.", ephemeral=True)
            return

        try:
            team = await Team.get(player=player)
        except DoesNotExist:
            await interaction.followup.send("No lineup set yet.", ephemeral=True)
            return

        lines: list[str] = []
        total_atk = total_hp = 0
        for pos in ("PG", "SG", "SF", "PF", "C"):
            slot_id = team.get_slot_id(pos)
            if slot_id:
                try:
                    inst = await BallInstance.get(pk=slot_id).prefetch_related("ball")
                    stars = "⭐" * max(1, round(inst.ball.rarity * 5))
                    lines.append(
                        f"**{pos}** · {inst.ball.country}  {stars}\n"
                        f"  ⚔ {inst.attack}  🛡 {inst.health}"
                    )
                    total_atk += inst.attack
                    total_hp += inst.health
                except DoesNotExist:
                    lines.append(f"**{pos}** · *(card no longer owned)*")
            else:
                lines.append(f"**{pos}** · *Empty*")

        embed = discord.Embed(
            title=f"🏀 {target.display_name}'s Lineup",
            description="\n".join(lines),
            color=0xE8501A,
        )
        embed.add_field(name="Team Totals", value=f"⚔ {total_atk}  🛡 {total_hp}", inline=False)
        if not team.is_complete():
            embed.set_footer(text="⚠️ Lineup is not complete — use /team add or /team best")
        await interaction.followup.send(embed=embed, ephemeral=True)
