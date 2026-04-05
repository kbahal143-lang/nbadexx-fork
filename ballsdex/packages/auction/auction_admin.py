import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from ballsdex.core.models import Ball, BallInstance
from ballsdex.core.utils.transformers import BallTransform, SpecialTransform
from ballsdex.packages.auction.models import Auction, AuctionBid
from ballsdex.packages.coins.models import PlayerMoney
from ballsdex.core.models import Player
from ballsdex.settings import settings

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.auction.admin")

DURATION_RE = re.compile(r"(\d+)\s*([mhd])", re.IGNORECASE)

DURATION_SUGGESTIONS = [
    app_commands.Choice(name="30 minutes", value="30m"),
    app_commands.Choice(name="1 hour", value="1h"),
    app_commands.Choice(name="2 hours", value="2h"),
    app_commands.Choice(name="6 hours", value="6h"),
    app_commands.Choice(name="12 hours", value="12h"),
    app_commands.Choice(name="1 day", value="1d"),
    app_commands.Choice(name="3 days", value="3d"),
    app_commands.Choice(name="7 days", value="7d"),
]


def parse_duration(text: str) -> int | None:
    matches = DURATION_RE.findall(text)
    if not matches:
        return None
    total = 0
    for val, unit in matches:
        num = int(val)
        unit = unit.lower()
        if unit == "m":
            total += num * 60
        elif unit == "h":
            total += num * 3600
        elif unit == "d":
            total += num * 86400
    return total if total > 0 else None


class AuctionAdmin(app_commands.Group):
    """Admin commands for the auction system."""

    async def duration_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        if not current:
            return DURATION_SUGGESTIONS[:25]
        filtered = [
            c
            for c in DURATION_SUGGESTIONS
            if current.lower() in c.value.lower()
            or current.lower() in c.name.lower()
        ]
        if not filtered and parse_duration(current) is not None:
            secs = parse_duration(current)
            if secs and secs >= 60:
                if secs >= 86400:
                    label = f"{secs // 86400}d"
                elif secs >= 3600:
                    label = f"{secs // 3600}h"
                else:
                    label = f"{secs // 60}m"
                filtered = [app_commands.Choice(name=label, value=current)]
        return filtered[:25]

    @app_commands.command(name="create")
    @app_commands.describe(
        countryball="The NBA card to auction",
        duration="Duration (e.g. 30m, 2h, 1d)",
        special="Special variant (optional)",
        min_bid="Minimum starting bid in coins (default: 100)",
        min_increase="Minimum bid increment in coins (default: 100)",
        buyout="Instant-buy price in coins (optional)",
    )
    @app_commands.checks.has_any_role(*settings.root_role_ids, *settings.admin_role_ids)
    @app_commands.autocomplete(duration=duration_autocomplete)
    async def auction_create(
        self,
        interaction: discord.Interaction["BallsDexBot"],
        countryball: BallTransform,
        duration: str,
        special: SpecialTransform | None = None,
        min_bid: int = 100,
        min_increase: int = 100,
        buyout: int | None = None,
    ):
        """Create a new auction for an NBA card."""
        if interaction.response.is_done():
            return

        await interaction.response.defer(ephemeral=True)

        if not countryball:
            return

        secs = parse_duration(duration)
        if not secs or secs < 60:
            await interaction.followup.send(
                "Invalid duration. Use formats like `30m`, `2h`, `1d`. "
                "Minimum duration is 1 minute.",
                ephemeral=True,
            )
            return

        if min_bid < 1:
            await interaction.followup.send(
                "Minimum bid must be at least 1 coin.", ephemeral=True
            )
            return

        if min_increase < 1:
            await interaction.followup.send(
                "Minimum increase must be at least 1 coin.", ephemeral=True
            )
            return

        if buyout is not None and buyout < min_bid:
            await interaction.followup.send(
                "Buyout price must be at least the minimum bid.", ephemeral=True
            )
            return

        active = await Auction.filter(status="active").count()
        if active > 0:
            await interaction.followup.send(
                "There is already an active auction. End it first with "
                "`/admin auction end` before creating a new one.",
                ephemeral=True,
            )
            return

        now = datetime.now(timezone.utc)
        end_time = now + timedelta(seconds=secs)

        auction = await Auction.create(
            ball=countryball,
            special=special,
            min_bid=min_bid,
            min_increment=min_increase,
            buyout_price=buyout,
            end_time=end_time,
            original_end_time=end_time,
            created_by_id=interaction.user.id,
            channel_id=interaction.channel_id,
        )

        from ballsdex.packages.auction.cog import AuctionCog

        cog: AuctionCog | None = interaction.client.get_cog("AuctionCog")

        embed = discord.Embed(
            title=f"🏷️ Auction — {countryball.country}", color=0xFFD700
        )

        emoji = interaction.client.get_emoji(countryball.emoji_id)
        emoji_str = str(emoji) if emoji else ""
        if special:
            embed.description = f"{emoji_str}  **Special:** {special.name}"
        else:
            embed.description = f"{emoji_str}"

        embed.add_field(
            name="💰 Min Bid", value=f"{min_bid:,} coins", inline=True
        )
        embed.add_field(
            name="📈 Min Increase", value=f"{min_increase:,} coins", inline=True
        )
        buyout_text = f"{buyout:,} coins" if buyout else "N/A"
        embed.add_field(name="🔥 Buyout", value=buyout_text, inline=True)
        embed.add_field(
            name="🏆 Current Bid", value="No bids yet", inline=False
        )
        end_ts = int(end_time.timestamp())
        embed.add_field(
            name="⏰ Ends",
            value=f"<t:{end_ts}:R> (<t:{end_ts}:f>)",
            inline=False,
        )
        embed.set_footer(text="Use /auction bid to place your bid!")

        image_path = os.path.join("admin_panel/media", countryball.collection_card)
        file = None
        if os.path.exists(image_path):
            file = discord.File(image_path, filename="card.png")
            embed.set_image(url="attachment://card.png")

        if file:
            msg = await interaction.channel.send(embed=embed, file=file)
        else:
            msg = await interaction.channel.send(embed=embed)

        if msg.attachments:
            auction.image_url = msg.attachments[0].url
        elif msg.embeds and msg.embeds[0].image and msg.embeds[0].image.url:
            raw_url = msg.embeds[0].image.url
            if not raw_url.startswith("attachment://"):
                auction.image_url = raw_url

        auction.message_id = msg.id
        auction.channel_id = msg.channel.id
        await auction.save(
            update_fields=["message_id", "channel_id", "image_url"]
        )

        await interaction.followup.send(
            f"✅ Auction created for **{countryball.country}**! "
            f"Ends <t:{end_ts}:R>.",
            ephemeral=True,
        )
        log.info(
            f"Admin {interaction.user} created auction {auction.pk} for "
            f"{countryball.country} (special={special}, min_bid={min_bid}, "
            f"increment={min_increase}, buyout={buyout}, duration={secs}s)"
        )

    @app_commands.command(name="end")
    @app_commands.checks.has_any_role(*settings.root_role_ids, *settings.admin_role_ids)
    async def auction_end(
        self,
        interaction: discord.Interaction["BallsDexBot"],
    ):
        """End the current active auction early."""
        await interaction.response.defer(ephemeral=True)

        auction = await Auction.filter(status="active").order_by("-created_at").first()
        if not auction:
            await interaction.followup.send(
                "There is no active auction to end.", ephemeral=True
            )
            return

        cog: "AuctionCog | None" = interaction.client.get_cog("AuctionCog")
        if not cog:
            await interaction.followup.send(
                "Auction system is not loaded.", ephemeral=True
            )
            return

        lock = cog._get_lock(auction.pk)
        async with lock:
            await auction.refresh_from_db()
            if auction.status != "active":
                await interaction.followup.send(
                    "This auction has already ended.", ephemeral=True
                )
                return

            await cog._end_auction(auction)

        try:
            await auction.fetch_related("ball")
            ball_name = auction.ball.country
        except Exception:
            ball_name = f"Auction #{auction.pk}"

        await interaction.followup.send(
            f"✅ Auction for **{ball_name}** has been ended.",
            ephemeral=True,
        )
        log.info(f"Admin {interaction.user} ended auction {auction.pk}")

    @app_commands.command(name="cancel")
    @app_commands.checks.has_any_role(*settings.root_role_ids, *settings.admin_role_ids)
    async def auction_cancel(
        self,
        interaction: discord.Interaction["BallsDexBot"],
    ):
        """Cancel the current active auction and refund the top bidder."""
        await interaction.response.defer(ephemeral=True)

        auction = await Auction.filter(status="active").order_by("-created_at").first()
        if not auction:
            await interaction.followup.send(
                "There is no active auction to cancel.", ephemeral=True
            )
            return

        cog: "AuctionCog | None" = interaction.client.get_cog("AuctionCog")
        if not cog:
            await interaction.followup.send(
                "Auction system is not loaded.", ephemeral=True
            )
            return

        lock = cog._get_lock(auction.pk)
        async with lock:
            await auction.refresh_from_db()
            if auction.status != "active":
                await interaction.followup.send(
                    "This auction has already ended.", ephemeral=True
                )
                return

            async with in_transaction():
                if auction.current_bidder_id:
                    prev_player = await Player.get(discord_id=auction.current_bidder_id)
                    prev_money, _ = await PlayerMoney.get_or_create(player=prev_player)
                    prev_money.coins += auction.current_bid
                    await prev_money.save(update_fields=["coins"])

                auction.status = "cancelled"
                await auction.save(update_fields=["status"])

            if auction.current_bidder_id:
                try:
                    user = interaction.client.get_user(auction.current_bidder_id)
                    if not user:
                        user = await interaction.client.fetch_user(
                            auction.current_bidder_id
                        )
                    await user.send(
                        f"⚠️ The auction has been cancelled by an admin.\n"
                        f"Your **{auction.current_bid:,}** coins have been refunded."
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass

            await cog._update_embed(auction, cancelled=True)

        cog._locks.pop(auction.pk, None)

        try:
            await auction.fetch_related("ball")
            ball_name = auction.ball.country
        except Exception:
            ball_name = f"Auction #{auction.pk}"

        await interaction.followup.send(
            f"✅ Auction for **{ball_name}** has been cancelled.",
            ephemeral=True,
        )
        log.info(f"Admin {interaction.user} cancelled auction {auction.pk}")

    @app_commands.command(name="history")
    @app_commands.checks.has_any_role(*settings.root_role_ids, *settings.admin_role_ids)
    async def auction_history(
        self,
        interaction: discord.Interaction["BallsDexBot"],
    ):
        """View recent auction history with details."""
        await interaction.response.defer(ephemeral=True)

        auctions = (
            await Auction.all()
            .order_by("-created_at")
            .limit(20)
            .prefetch_related("ball")
        )

        if not auctions:
            await interaction.followup.send(
                "No auctions have been created yet.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="📜 Auction History", color=0xFFD700
        )

        for a in auctions[:10]:
            ball_name = a.ball.country if hasattr(a.ball, "country") else f"Ball #{a.ball_id}"

            status_icon = {
                "active": "🟢",
                "ended": "✅",
                "cancelled": "❌",
            }.get(a.status, "❓")

            created_ts = int(a.created_at.timestamp())

            if a.current_bidder_id:
                winner_text = f"Winner: <@{a.current_bidder_id}> — **{a.current_bid:,}** coins"
            else:
                winner_text = "No bids"

            if a.winner_instance_id:
                winner_text += f" — Card `#{a.winner_instance_id:0X}`"

            bid_count = await AuctionBid.filter(auction=a).count()

            embed.add_field(
                name=f"{status_icon} {ball_name} — <t:{created_ts}:d>",
                value=(
                    f"{winner_text}\n"
                    f"Min bid: {a.min_bid:,} | Increment: {a.min_increment:,} | "
                    f"Buyout: {a.buyout_price:,} coins\n"
                    f"Total bids: {bid_count}"
                    if a.buyout_price
                    else (
                        f"{winner_text}\n"
                        f"Min bid: {a.min_bid:,} | Increment: {a.min_increment:,} | "
                        f"Buyout: N/A\n"
                        f"Total bids: {bid_count}"
                    )
                ),
                inline=False,
            )

        if len(auctions) > 10:
            embed.set_footer(text=f"Showing 10 of {len(auctions)} recent auctions")

        await interaction.followup.send(embed=embed, ephemeral=True)
