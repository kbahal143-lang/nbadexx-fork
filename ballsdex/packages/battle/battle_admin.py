"""
Battle admin command group — registered as /admin battle via the main Admin cog.
Follows the same app_commands.Group pattern as CoinsAdmin / PacksAdmin.
"""

import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from tortoise.expressions import Q

from ballsdex.core.utils.transformers import BallTransform

from .models import MatchResult, PlayerPosition

log = logging.getLogger("ballsdex.packages.battle.admin")

POSITION_CHOICES = [
    app_commands.Choice(name="Point Guard (PG)", value="PG"),
    app_commands.Choice(name="Shooting Guard (SG)", value="SG"),
    app_commands.Choice(name="Small Forward (SF)", value="SF"),
    app_commands.Choice(name="Power Forward (PF)", value="PF"),
    app_commands.Choice(name="Center (C)", value="C"),
]

POSITION_WITH_NONE = POSITION_CHOICES + [
    app_commands.Choice(name="None (clear secondary)", value="none"),
]


class BattleAdmin(app_commands.Group):
    """Admin commands for the battle system."""

    @app_commands.command(name="setposition")
    @app_commands.describe(
        ball="The player card to assign a position to",
        primary="Primary basketball position",
        secondary="Secondary basketball position (optional — choose 'None' to clear it)",
    )
    @app_commands.choices(primary=POSITION_CHOICES, secondary=POSITION_WITH_NONE)
    async def setposition(
        self,
        interaction: discord.Interaction,
        ball: BallTransform,
        primary: app_commands.Choice[str],
        secondary: app_commands.Choice[str] | None = None,
    ):
        """Set the basketball position(s) for a player card."""
        await interaction.response.defer(ephemeral=True)

        sec_value = secondary.value if secondary and secondary.value != "none" else None
        pp, created = await PlayerPosition.get_or_create(ball_id=ball.pk)
        pp.primary = primary.value
        pp.secondary = sec_value
        await pp.save()

        action = "Created" if created else "Updated"
        pos_str = f"{primary.value}/{sec_value}" if sec_value else primary.value
        await interaction.followup.send(
            f"✅ {action} position for **{ball.country}**: **{pos_str}**",
            ephemeral=True,
        )
        log.info(
            f"Admin {interaction.user} set position for ball {ball.pk} ({ball.country})"
            f" to {pos_str}"
        )

    @app_commands.command(name="matchstats")
    @app_commands.describe(member="The Discord member whose battle stats you want to check")
    async def matchstats(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
    ):
        """View a player's win/loss record and today's reward usage."""
        await interaction.response.defer(ephemeral=True)

        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        total = await MatchResult.filter(
            Q(challenger_discord_id=member.id) | Q(challenged_discord_id=member.id)
        ).count()
        wins = await MatchResult.filter(winner_discord_id=member.id).count()
        losses = total - wins
        today_count = await MatchResult.filter(
            Q(challenger_discord_id=member.id) | Q(challenged_discord_id=member.id),
            played_at__gte=today_start,
        ).count()

        embed = discord.Embed(
            title=f"⚔️  Battle Stats — {member.display_name}",
            color=0xE8501A,
        )
        embed.add_field(name="🏆 Wins", value=str(wins), inline=True)
        embed.add_field(name="❌ Losses", value=str(losses), inline=True)
        embed.add_field(name="📊 Total Matches", value=str(total), inline=True)
        embed.add_field(
            name="🪙 Daily Rewards Used",
            value=f"{today_count} / 10 today",
            inline=False,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
