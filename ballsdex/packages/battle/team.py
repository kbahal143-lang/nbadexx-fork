"""
/team command group for the Battle package.
Commands work with any tradeable card that has an assigned basketball position.
"""

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands
from tortoise.exceptions import DoesNotExist
from tortoise.expressions import Q

from ballsdex.core.models import Ball, BallInstance, Player
from ballsdex.core.utils.transformers import BallInstanceTransform
from ballsdex.settings import settings

from .models import PlayerPosition, Team
from .positions import POSITION_LABELS

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.battle")

# ──────────────────────────────────────────────────────────
# FILL IN: the Discord server (guild) ID where battle
# commands should be allowed. Teams are blocked everywhere else.
# ──────────────────────────────────────────────────────────
BATTLE_GUILD_ID = 1440962506796433519

POSITION_CHOICES = [
    app_commands.Choice(name="Point Guard (PG)", value="PG"),
    app_commands.Choice(name="Shooting Guard (SG)", value="SG"),
    app_commands.Choice(name="Small Forward (SF)", value="SF"),
    app_commands.Choice(name="Power Forward (PF)", value="PF"),
    app_commands.Choice(name="Center (C)", value="C"),
]


async def get_assigned_position(ball: Ball) -> PlayerPosition | None:
    """Return the position explicitly assigned to this ball, if one exists."""
    return await PlayerPosition.get_or_none(ball_id=ball.pk)


async def find_ineligible_slots(slots: dict[str, BallInstance | None]) -> list[str]:
    """Return lineup slots whose cards lack an assigned or matching position."""
    ineligible: list[str] = []
    for position, instance in slots.items():
        if instance is None:
            continue
        position_record = await get_assigned_position(instance.ball)
        if position_record is None or not position_record.allows(position):
            ineligible.append(position)
    return ineligible


async def find_ineligible_team_slots(team: Team) -> list[str]:
    """Validate every filled team slot against its admin-assigned position."""
    slots: dict[str, BallInstance | None] = {}
    for position in ("PG", "SG", "SF", "PF", "C"):
        instance_id = team.get_slot_id(position)
        slots[position] = (
            await BallInstance.get_or_none(pk=instance_id).prefetch_related("ball")
            if instance_id
            else None
        )
    return await find_ineligible_slots(slots)


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
    return inst.battle_attack * ow + inst.battle_health * dw


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

        inst = await BallInstance.get(pk=card.pk).prefetch_related("ball")
        ball = inst.ball
        pos = position.value

        # 1. Must belong to the user
        player = await Player.get_or_none(discord_id=interaction.user.id)
        if not player or inst.player_id != player.pk:
            await interaction.followup.send("❌ You don't own that card.", ephemeral=True)
            return

        # 2. Must have an administrator-assigned position
        pp = await get_assigned_position(ball)
        if pp is None:
            await interaction.followup.send(
                "This card is not eligible for battle.",
                ephemeral=True,
            )
            return

        # 3. Position must be allowed
        if not pp.allows(pos):
            allowed = pp.display()
            await interaction.followup.send(
                f"❌ **{ball.country}** plays **{allowed}**, not **{pos}**.\n"
                f"You can only place them at their correct position(s).",
                ephemeral=True,
            )
            return

        # 4. Card must not be locked elsewhere (match stake, bet, etc.)
        if not inst.tradeable:
            await interaction.followup.send(
                f"❌ **{ball.country}** is currently locked (staked in a match or bet).",
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

        old_slot_id = team.get_slot_id(pos)
        team.set_slot_id(pos, inst.pk)
        await team.save()

        if old_slot_id:
            await BallInstance.filter(pk=old_slot_id).update(tradeable=True)
        await BallInstance.filter(pk=inst.pk).update(tradeable=False)

        await interaction.followup.send(
            f"✅ **{ball.country}** [{pp.display()}] added to your **{POSITION_LABELS[pos]}** slot!\n"
            f"⚔ {inst.battle_attack}  🛡 {inst.battle_health}",
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
        old_slot_id = team.get_slot_id(pos)
        if not old_slot_id:
            await interaction.followup.send(
                f"The **{POSITION_LABELS[pos]}** slot is already empty.", ephemeral=True
            )
            return

        team.set_slot_id(pos, None)
        await team.save()
        await BallInstance.filter(pk=old_slot_id).update(tradeable=True)
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

        old_ids = [team.get_slot_id(pos) for pos in ("PG", "SG", "SF", "PF", "C")]
        old_ids = [i for i in old_ids if i]
        for pos in ("PG", "SG", "SF", "PF", "C"):
            team.set_slot_id(pos, None)
        await team.save()
        if old_ids:
            await BallInstance.filter(pk__in=old_ids).update(tradeable=True)
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

        team, _ = await Team.get_or_create(player=player)
        current_lineup_ids = [
            team.get_slot_id(p) for p in ("PG", "SG", "SF", "PF", "C")
        ]
        current_lineup_ids = [i for i in current_lineup_ids if i]

        all_insts = (
            await BallInstance.filter(player=player)
            .filter(Q(tradeable=True) | Q(pk__in=current_lineup_ids))
            .prefetch_related("ball", "special")
        )

        eligible_insts = [
            i for i in all_insts if await get_assigned_position(i.ball) is not None
        ]
        if not eligible_insts:
            await interaction.followup.send(
                "You don't have any eligible cards. Cards need an assigned basketball "
                "position before they can be used in battle.",
                ephemeral=True,
            )
            return

        pos_map: dict[int, PlayerPosition] = {}
        for inst in eligible_insts:
            pp = await get_assigned_position(inst.ball)
            if pp:
                pos_map[inst.pk] = pp

        assigned: set[int] = set()
        assigned_balls: set[int] = set()
        result_lines: list[str] = []
        new_lineup_ids: list[int] = []

        for pos in ("PG", "SG", "SF", "PF", "C"):
            # Combine primary and secondary — best stats wins regardless of which it is
            candidates = [
                i for i in eligible_insts
                if i.pk in pos_map
                and pos_map[i.pk].allows(pos)
                and i.pk not in assigned
                and i.ball.pk not in assigned_balls
            ]

            if not candidates:
                team.set_slot_id(pos, None)
                result_lines.append(f"**{pos}** — No eligible card found")
                continue

            best = max(candidates, key=lambda i: _score_instance(i, pos))
            team.set_slot_id(pos, best.pk)
            assigned.add(best.pk)
            assigned_balls.add(best.ball.pk)
            new_lineup_ids.append(best.pk)
            result_lines.append(
                f"**{pos}** — {best.ball.country}  ⚔ {best.battle_attack}  🛡 {best.battle_health}"
            )

        await team.save()

        removed_ids = [i for i in current_lineup_ids if i not in new_lineup_ids]
        if removed_ids:
            await BallInstance.filter(pk__in=removed_ids).update(tradeable=True)
        if new_lineup_ids:
            await BallInstance.filter(pk__in=new_lineup_ids).update(tradeable=False)

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
                    inst = await BallInstance.get(pk=slot_id).prefetch_related("ball", "special")
                    if inst.player_id != player.pk:
                        lines.append(f"**{pos}** · *(card no longer owned)*")
                    else:
                        spec_emoji = inst.special_emoji(interaction.client)
                        spec_name = f" ({inst.specialcard.name})" if inst.specialcard else ""
                        lines.append(
                            f"**{pos}** · {spec_emoji}{inst.ball.country}{spec_name}\n"
                            f"  ⚔ {inst.battle_attack}  🛡 {inst.battle_health}"
                        )
                        total_atk += inst.battle_attack
                        total_hp += inst.battle_health
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
