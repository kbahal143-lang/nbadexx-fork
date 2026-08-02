"""
/profile and /set showcase commands for the Battle package.

/profile [member]      — view all-time battle stats + showcase card
/set showcase card art — set the card displayed at the bottom of your profile
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands
from tortoise.exceptions import DoesNotExist

from ballsdex.core.models import Ball, BallInstance, Player
from ballsdex.core.utils.transformers import BallInstanceTransform

from .models import BattleCardStats, BattleProfile, BattleShowcase

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.battle")

BATTLE_GUILD_ID = 1440962506796433519
MEDIA_ROOT = "./admin_panel/media/"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _winrate_bar(wins: int, total: int, width: int = 12) -> str:
    """Unicode block progress bar  ████████░░░░  XX.X%"""
    if total == 0:
        return "░" * width + "  —"
    rate = wins / total
    filled = round(rate * width)
    pct = rate * 100
    return f"{'█' * filled}{'░' * (width - filled)}  {pct:.1f}%"


def _streak_label(streak: int) -> str:
    if streak <= 0:
        return "—"
    if streak == 1:
        return f"🔥  **{streak}** win"
    if streak <= 4:
        return f"🔥  **{streak}** in a row"
    if streak <= 9:
        return f"🔥🔥  **{streak}** in a row"
    return f"🔥🔥🔥  **{streak}** in a row"


async def _get_showcase_file(
    interaction: discord.Interaction,
    showcase: BattleShowcase,
    owner_discord_id: int,
) -> discord.File | None:
    """
    Returns a discord.File for the showcase card.
    Fetches the exact BallInstance the user chose, so specials render correctly.
    Auto-clears the showcase if the card was traded away or deleted.

    - spawn art  → read wild_card image directly from media
    - card art   → generate the full card via draw_card() (special background, frame, etc.)
    """
    try:
        inst = (
            await BallInstance.filter(pk=showcase.instance_id)
            .prefetch_related("ball", "special", "player")
            .first()
        )
        if inst is None or inst.deleted:
            await showcase.delete()
            return None

        # Auto-clear showcase if the card was traded away or quicksold
        if inst.player.discord_id != owner_discord_id:
            await showcase.delete()
            return None

        if showcase.art_type == "spawn":
            path = MEDIA_ROOT + inst.countryball.wild_card
            if not os.path.isfile(path):
                return None
            ext = path.rsplit(".", 1)[-1].lower()
            return discord.File(path, filename=f"showcase.{ext}")

        # card art — full generated card (includes special background, overlays, stats)
        with ThreadPoolExecutor() as pool:
            buffer = await interaction.client.loop.run_in_executor(pool, inst.draw_card)
        return discord.File(buffer, filename="showcase.webp")

    except DoesNotExist:
        return None
    except Exception:
        log.exception("Failed to build showcase file")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# /profile
# ─────────────────────────────────────────────────────────────────────────────

class ProfileCog(commands.Cog):
    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot

    @app_commands.command(name="profile")
    @app_commands.guild_only()
    @app_commands.describe(member="View another player's battle profile (optional)")
    async def profile(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
    ):
        """View your all-time battle stats and showcase card."""
        if interaction.guild_id != BATTLE_GUILD_ID:
            await interaction.response.send_message(
                "Battle commands are not available in this server.", ephemeral=True
            )
            return

        await interaction.response.defer()

        target = member or interaction.user

        # ── Fetch data ───────────────────────────────────────────────────────
        profile, _ = await BattleProfile.get_or_create(discord_id=target.id)
        total = profile.wins + profile.losses

        # Top scoring card — find user's instance to pull special emoji
        top_scorer_value = "—"
        top_stat = (
            await BattleCardStats.filter(discord_id=target.id)
            .order_by("-total_pts")
            .first()
        )
        if top_stat and top_stat.total_pts > 0:
            try:
                # Look up the exact instance that earned those points
                top_inst = (
                    await BallInstance.get(pk=top_stat.instance_id)
                    .prefetch_related("ball", "special")
                )
                emoji_str = ""
                if top_inst.specialcard:
                    emoji_str = top_inst.special_emoji(interaction.client)
                top_scorer_value = (
                    f"{emoji_str}**{top_inst.ball.country}**\n*{top_stat.total_pts:,} pts*"
                )
            except DoesNotExist:
                # Instance was deleted (shouldn't happen — stats are cleared on delete)
                pass

        # Showcase
        showcase = await BattleShowcase.get_or_none(discord_id=target.id)

        # ── Build embed ──────────────────────────────────────────────────────
        embed = discord.Embed(color=0x0D1B2A)

        embed.set_author(
            name=f"{target.display_name}'s Profile",
            icon_url=target.display_avatar.url,
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        embed.add_field(name="🏆  Wins",   value=f"**{profile.wins:,}**",   inline=True)
        embed.add_field(name="❌  Losses", value=f"**{profile.losses:,}**", inline=True)
        embed.add_field(name="⚡  Played", value=f"**{total:,}**",          inline=True)

        embed.add_field(
            name="📊  Win Rate",
            value=f"`{_winrate_bar(profile.wins, total)}`",
            inline=False,
        )

        embed.add_field(
            name="🔥  Current Streak",
            value=_streak_label(profile.current_streak),
            inline=True,
        )
        embed.add_field(
            name="👑  Top Scorer",
            value=top_scorer_value,
            inline=True,
        )

        # ── Showcase image ────────────────────────────────────────────────────
        files: list[discord.File] = []
        if showcase:
            showcase_file = await _get_showcase_file(interaction, showcase, target.id)
            if showcase_file:
                files.append(showcase_file)
                embed.set_image(url=f"attachment://{showcase_file.filename}")

        embed.set_footer(text="NBADex")

        await interaction.followup.send(embed=embed, files=files)


# ─────────────────────────────────────────────────────────────────────────────
# /set showcase
# ─────────────────────────────────────────────────────────────────────────────

class SetCog(commands.GroupCog, group_name="set"):
    """Configure your battle profile settings."""

    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id != BATTLE_GUILD_ID:
            await interaction.response.send_message(
                "Battle commands are not available in this server.", ephemeral=True
            )
            return False
        return True

    @app_commands.command(name="showcase")
    @app_commands.describe(
        card="The NBA card to feature on your profile",
        art="Which artwork to display — spawn art or the full generated card",
    )
    @app_commands.choices(art=[
        app_commands.Choice(name="Spawn Art", value="spawn"),
        app_commands.Choice(name="Card Art",  value="card"),
    ])
    async def set_showcase(
        self,
        interaction: discord.Interaction,
        card: BallInstanceTransform,
        art: app_commands.Choice[str],
    ):
        """Set the card shown at the bottom of your /profile."""
        await interaction.response.defer(ephemeral=True)

        inst = await BallInstance.get(pk=card.pk).prefetch_related("ball", "special")

        # Verify ownership
        player = await Player.get_or_none(discord_id=interaction.user.id)
        if not player or inst.player_id != player.pk:
            await interaction.followup.send("❌ You don't own that card.", ephemeral=True)
            return

        ball = inst.countryball
        art_type = art.value

        # For spawn art, verify the file exists
        if art_type == "spawn":
            path = MEDIA_ROOT + ball.wild_card
            if not os.path.isfile(path):
                await interaction.followup.send(
                    f"❌ The spawn art for **{ball.country}** isn't available yet. "
                    "Try **Card Art** instead.",
                    ephemeral=True,
                )
                return

        # Save the exact instance ID so /profile renders this card's specific special
        showcase, created = await BattleShowcase.get_or_create(
            discord_id=interaction.user.id,
            defaults={"instance_id": inst.pk, "art_type": art_type},
        )
        if not created:
            showcase.instance_id = inst.pk
            showcase.art_type = art_type
            await showcase.save()

        emoji_str = inst.special_emoji(interaction.client) if inst.specialcard else ""
        art_label = "Spawn Art" if art_type == "spawn" else "Card Art"
        await interaction.followup.send(
            f"✅ Showcase set!  {emoji_str}**{ball.country}**  ·  *{art_label}*\n"
            "Use `/profile` to see it in action.",
            ephemeral=True,
        )
