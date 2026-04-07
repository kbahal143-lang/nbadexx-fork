"""
Collector admin command group — registered as /admin collector.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from tortoise.exceptions import DoesNotExist, IntegrityError

from ballsdex.core.models import Ball, BallInstance, Player
from ballsdex.core.utils.transformers import BallTransform

from .models import CollectorCard, CollectorRequirement, PlayerCollectorCard

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.collector.admin")

Interaction = discord.Interaction["BallsDexBot"]


class CollectorAdmin(app_commands.Group):
    """Collector card admin tools."""

    @app_commands.command(name="give")
    @app_commands.describe(
        user="Target player",
        card_name="Tier name (e.g. Bronze)",
        collectible="Card to award the tier for",
    )
    async def collector_give(
        self,
        interaction: Interaction,
        user: discord.User,
        card_name: str,
        collectible: BallTransform,
    ):
        """Give a collector card, bypassing requirements."""
        await interaction.response.defer(ephemeral=True)

        card = await CollectorCard.filter(name__icontains=card_name, enabled=True).first()
        if not card:
            await interaction.followup.send(
                f"Collector tier **{card_name}** not found. "
                f"Check the name and make sure it is enabled.",
                ephemeral=True,
            )
            return

        tier_em = f"{card.emoji} " if card.emoji else ""

        if not card.special_id:
            await interaction.followup.send(
                f"**{tier_em}{card.name}** doesn't have a special background configured — "
                f"set one in the admin panel first.",
                ephemeral=True,
            )
            return

        player, _ = await Player.get_or_create(discord_id=user.id)

        already = await PlayerCollectorCard.filter(
            player=player, card=card, ball=collectible
        ).exists()
        if already:
            await interaction.followup.send(
                f"{user.mention} already has **{tier_em}{card.name}** for "
                f"**{collectible.country}**.",
                ephemeral=True,
            )
            return

        new_instance = await BallInstance.create(
            player=player,
            ball=collectible,
            special_id=card.special_id,
            attack_bonus=0,
            health_bonus=0,
            tradeable=False,
        )

        try:
            await PlayerCollectorCard.create(
                player=player,
                card=card,
                ball=collectible,
                ball_instance=new_instance,
            )
        except IntegrityError:
            await new_instance.delete()
            await interaction.followup.send(
                f"{user.mention} already has **{tier_em}{card.name}** for "
                f"**{collectible.country}** (race condition).",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"✅ Gave **{tier_em}{card.name}** ({collectible.country}) to {user.mention}.",
            ephemeral=True,
        )
        log.info(
            f"Admin {interaction.user} gave collector card {card.name} "
            f"({collectible.country}) to player {user.id}"
        )

    @app_commands.command(name="revoke")
    @app_commands.describe(
        user="Target player",
        card_name="Tier name",
        collectible="Card to revoke the tier for",
    )
    async def collector_revoke(
        self,
        interaction: Interaction,
        user: discord.User,
        card_name: str,
        collectible: BallTransform,
    ):
        """Revoke a collector card from a player."""
        await interaction.response.defer(ephemeral=True)

        card = await CollectorCard.filter(name__icontains=card_name).first()
        if not card:
            await interaction.followup.send(
                f"Collector tier **{card_name}** not found.", ephemeral=True
            )
            return

        tier_em = f"{card.emoji} " if card.emoji else ""

        try:
            player = await Player.get(discord_id=user.id)
        except DoesNotExist:
            await interaction.followup.send(
                f"{user.mention} has no collector cards.", ephemeral=True
            )
            return

        holder = await PlayerCollectorCard.get_or_none(
            player=player, card=card, ball=collectible
        )
        if not holder:
            await interaction.followup.send(
                f"{user.mention} doesn't have **{tier_em}{card.name}** for "
                f"**{collectible.country}**.",
                ephemeral=True,
            )
            return

        if holder.ball_instance_id:
            inst = await BallInstance.get_or_none(pk=holder.ball_instance_id)
            if inst:
                inst.deleted = True
                await inst.save(update_fields=["deleted"])

        await holder.delete()

        await interaction.followup.send(
            f"✅ Revoked **{tier_em}{card.name}** ({collectible.country}) from "
            f"{user.mention}.",
            ephemeral=True,
        )
        log.info(
            f"Admin {interaction.user} revoked collector card {card.name} "
            f"({collectible.country}) from player {user.id}"
        )

    @app_commands.command(name="sync")
    async def collector_sync(self, interaction: Interaction):
        """Run a revoke check on all collector cards."""
        await interaction.response.defer(ephemeral=True)

        from .cog import CollectorCog

        cog: CollectorCog | None = interaction.client.cogs.get("collector")  # type: ignore
        if not cog:
            await interaction.followup.send(
                "Collector cog not found.", ephemeral=True
            )
            return

        try:
            await cog._check_and_revoke_all()
        except Exception as e:
            await interaction.followup.send(
                f"Sync failed: {e}", ephemeral=True
            )
            return

        await interaction.followup.send(
            "✅ Collector revoke sync completed.", ephemeral=True
        )

    @app_commands.command(name="list")
    @app_commands.describe(user="Target player")
    async def collector_list_admin(
        self, interaction: Interaction, user: discord.User
    ):
        """List collector cards owned by a player."""
        await interaction.response.defer(ephemeral=True)

        try:
            player = await Player.get(discord_id=user.id)
        except DoesNotExist:
            await interaction.followup.send(
                f"{user.mention} has no collector cards.", ephemeral=True
            )
            return

        holders = (
            await PlayerCollectorCard.filter(player=player)
            .prefetch_related("card", "ball")
            .order_by("ball__rarity", "card__name")
            .all()
        )
        if not holders:
            await interaction.followup.send(
                f"{user.mention} has no collector cards.", ephemeral=True
            )
            return

        lines = []
        for h in holders:
            tier_em = f"{h.card.emoji} " if h.card.emoji else ""
            lines.append(
                f"• {h.ball.country} — **{tier_em}{h.card.name}** "
                f"(claimed <t:{int(h.claimed_at.timestamp())}:R>)"
            )

        embed = discord.Embed(
            title=f"🏅 {user.display_name}'s Collector Cards",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
