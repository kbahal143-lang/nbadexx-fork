import asyncio
import logging
import os
import random
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands, tasks
from tortoise.exceptions import DoesNotExist
from tortoise.transactions import in_transaction

from ballsdex.core.models import Ball, BallInstance, Player
from ballsdex.packages.auction.models import Auction, AuctionBid
from ballsdex.packages.coins.models import PlayerMoney
from ballsdex.settings import settings

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.auction")

AUCTION_GUILD_ID = 1440962506796433519
SNIPE_EXTENSION_SECS = 180


class AuctionCog(commands.GroupCog, group_name="auction"):
    """Player-facing auction commands."""

    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot
        self._locks: dict[int, asyncio.Lock] = {}

    def _get_lock(self, auction_id: int) -> asyncio.Lock:
        if auction_id not in self._locks:
            self._locks[auction_id] = asyncio.Lock()
        return self._locks[auction_id]

    async def cog_load(self):
        self.check_auctions.start()

    async def cog_unload(self):
        self.check_auctions.cancel()

    @tasks.loop(seconds=5)
    async def check_auctions(self):
        now = datetime.now(timezone.utc)
        ended = await Auction.filter(status="active", end_time__lte=now)
        for auction in ended:
            lock = self._get_lock(auction.pk)
            async with lock:
                await auction.refresh_from_db()
                if auction.status != "active":
                    continue
                try:
                    await self._end_auction(auction)
                except Exception:
                    log.exception(f"Error ending auction {auction.pk}")

    @check_auctions.before_loop
    async def before_check_auctions(self):
        await self.bot.wait_until_ready()

    async def _build_embed(
        self, auction: Auction, *, ended: bool = False, cancelled: bool = False
    ) -> discord.Embed:
        try:
            ball = auction.ball
            if not hasattr(ball, "country"):
                ball = await Ball.get(pk=auction.ball_id)
        except Exception:
            ball = await Ball.get(pk=auction.ball_id)

        special_name = None
        if auction.special_id:
            from ballsdex.core.models import Special
            try:
                sp = await Special.get(pk=auction.special_id)
                special_name = sp.name
            except DoesNotExist:
                pass

        emoji = self.bot.get_emoji(ball.emoji_id)
        emoji_str = str(emoji) if emoji else ""

        if cancelled:
            title = f"❌ Auction Cancelled — {ball.country}"
            color = 0xE74C3C
        elif ended:
            if auction.current_bidder_id:
                title = f"✅ Auction Ended — {ball.country}"
                color = 0x2ECC71
            else:
                title = f"❌ Auction Ended — {ball.country}"
                color = 0xE74C3C
        else:
            title = f"🏷️ Auction — {ball.country}"
            color = 0xFFD700

        embed = discord.Embed(title=title, color=color)

        if special_name:
            embed.description = f"{emoji_str}  **Special:** {special_name}"
        else:
            embed.description = f"{emoji_str}"

        if not ended and not cancelled:
            embed.add_field(
                name="💰 Min Bid",
                value=f"{auction.min_bid:,} coins",
                inline=True,
            )
            embed.add_field(
                name="📈 Min Increase",
                value=f"{auction.min_increment:,} coins",
                inline=True,
            )
            buyout_text = f"{auction.buyout_price:,} coins" if auction.buyout_price else "N/A"
            embed.add_field(name="🔥 Buyout", value=buyout_text, inline=True)

            if auction.current_bidder_id:
                embed.add_field(
                    name="🏆 Current Bid",
                    value=f"**{auction.current_bid:,}** coins by <@{auction.current_bidder_id}>",
                    inline=False,
                )
            else:
                embed.add_field(
                    name="🏆 Current Bid",
                    value="No bids yet",
                    inline=False,
                )

            end_ts = int(auction.end_time.timestamp())
            embed.add_field(
                name="⏰ Ends",
                value=f"<t:{end_ts}:R> (<t:{end_ts}:f>)",
                inline=False,
            )
            embed.set_footer(text="Use /auction bid to place your bid!")
        elif ended and not cancelled:
            if auction.current_bidder_id:
                embed.add_field(
                    name="🏆 Winner",
                    value=f"<@{auction.current_bidder_id}>",
                    inline=True,
                )
                embed.add_field(
                    name="💰 Winning Bid",
                    value=f"**{auction.current_bid:,}** coins",
                    inline=True,
                )
                if auction.winner_instance_id:
                    embed.add_field(
                        name="🎴 Card ID",
                        value=f"#{auction.winner_instance_id:0X}",
                        inline=True,
                    )
                embed.set_footer(text="Congratulations to the winner!")
            else:
                embed.add_field(
                    name="Result",
                    value="No bids were placed. The auction has ended.",
                    inline=False,
                )
        elif cancelled:
            if auction.current_bidder_id:
                embed.add_field(
                    name="💸 Refund",
                    value=f"<@{auction.current_bidder_id}> has been refunded **{auction.current_bid:,}** coins.",
                    inline=False,
                )
            embed.set_footer(text="This auction was cancelled by an admin.")

        if auction.image_url:
            embed.set_image(url=auction.image_url)

        return embed

    async def _update_embed(self, auction: Auction, **embed_kwargs):
        if not auction.channel_id or not auction.message_id:
            return
        try:
            channel = self.bot.get_channel(auction.channel_id)
            if not channel:
                return
            message = await channel.fetch_message(auction.message_id)
            embed = await self._build_embed(auction, **embed_kwargs)
            await message.edit(embed=embed, attachments=[])
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    async def _end_auction(self, auction: Auction):
        await auction.fetch_related("ball")
        ball = auction.ball

        if auction.current_bidder_id:
            winner_player, _ = await Player.get_or_create(
                discord_id=auction.current_bidder_id
            )
            instance = await BallInstance.create(
                ball=ball,
                player=winner_player,
                attack_bonus=random.randint(
                    -settings.max_attack_bonus, settings.max_attack_bonus
                ),
                health_bonus=random.randint(
                    -settings.max_health_bonus, settings.max_health_bonus
                ),
                special_id=auction.special_id,
            )
            auction.winner_instance_id = instance.pk
            auction.status = "ended"
            await auction.save(
                update_fields=["status", "winner_instance_id"]
            )

            await self._update_embed(auction, ended=True)

            try:
                user = self.bot.get_user(auction.current_bidder_id)
                if not user:
                    user = await self.bot.fetch_user(auction.current_bidder_id)
                await user.send(
                    f"🎉 Congratulations! You won the auction for **{ball.country}**!\n"
                    f"Winning bid: **{auction.current_bid:,}** coins\n"
                    f"Card ID: `#{instance.pk:0X}`"
                )
            except (discord.Forbidden, discord.HTTPException):
                pass

            log.info(
                f"Auction {auction.pk} ended — winner {auction.current_bidder_id} "
                f"bid {auction.current_bid}, card #{instance.pk:0X}"
            )
        else:
            auction.status = "ended"
            await auction.save(update_fields=["status"])
            await self._update_embed(auction, ended=True)
            log.info(f"Auction {auction.pk} ended with no bids")

        self._locks.pop(auction.pk, None)

    @app_commands.command(name="bid")
    @app_commands.describe(amount="The amount of coins to bid")
    async def auction_bid(
        self,
        interaction: discord.Interaction["BallsDexBot"],
        amount: int,
    ):
        """Place a bid on the current auction."""
        if interaction.guild_id != AUCTION_GUILD_ID:
            await interaction.response.send_message(
                "This command can only be used in the main server.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        auction = await Auction.filter(status="active").order_by("-created_at").first()
        if not auction:
            await interaction.followup.send(
                "There is no active auction right now.", ephemeral=True
            )
            return

        lock = self._get_lock(auction.pk)
        async with lock:
            await auction.refresh_from_db()
            if auction.status != "active":
                await interaction.followup.send(
                    "This auction has already ended.", ephemeral=True
                )
                return

            now = datetime.now(timezone.utc)
            if now >= auction.end_time:
                await interaction.followup.send(
                    "This auction has just ended.", ephemeral=True
                )
                return

            if amount <= 0:
                await interaction.followup.send(
                    "Your bid must be a positive number.", ephemeral=True
                )
                return

            if auction.current_bidder_id == interaction.user.id:
                await interaction.followup.send(
                    "You are already the highest bidder!", ephemeral=True
                )
                return

            if auction.current_bid == 0:
                if amount < auction.min_bid:
                    await interaction.followup.send(
                        f"Your bid must be at least **{auction.min_bid:,}** coins "
                        f"(the minimum bid).",
                        ephemeral=True,
                    )
                    return
            else:
                min_required = auction.current_bid + auction.min_increment
                if amount < min_required:
                    await interaction.followup.send(
                        f"Your bid must be at least **{min_required:,}** coins "
                        f"(current bid {auction.current_bid:,} + "
                        f"minimum increase {auction.min_increment:,}).",
                        ephemeral=True,
                    )
                    return

            is_buyout = (
                auction.buyout_price is not None and amount >= auction.buyout_price
            )
            if is_buyout:
                amount = auction.buyout_price

            player, _ = await Player.get_or_create(discord_id=interaction.user.id)
            money, _ = await PlayerMoney.get_or_create(player=player)

            if money.coins < amount:
                await interaction.followup.send(
                    f"You don't have enough coins. "
                    f"Your balance: **{money.coins:,}** coins, "
                    f"bid amount: **{amount:,}** coins.",
                    ephemeral=True,
                )
                return

            prev_bidder_id = auction.current_bidder_id
            prev_bid_amount = auction.current_bid

            async with in_transaction():
                money.coins -= amount
                await money.save(update_fields=["coins"])

                if prev_bidder_id:
                    prev_player = await Player.get(discord_id=prev_bidder_id)
                    prev_money, _ = await PlayerMoney.get_or_create(player=prev_player)
                    prev_money.coins += prev_bid_amount
                    await prev_money.save(update_fields=["coins"])

                auction.current_bid = amount
                auction.current_bidder_id = interaction.user.id

                remaining = (auction.end_time - now).total_seconds()
                if remaining < SNIPE_EXTENSION_SECS:
                    auction.end_time = now + timedelta(seconds=SNIPE_EXTENSION_SECS)

                await auction.save(
                    update_fields=[
                        "current_bid",
                        "current_bidder_id",
                        "end_time",
                    ]
                )

                await AuctionBid.create(
                    auction=auction,
                    bidder_discord_id=interaction.user.id,
                    amount=amount,
                )

            if is_buyout:
                await interaction.followup.send(
                    f"🔥 **BUYOUT!** You bought it for **{amount:,}** coins!",
                    ephemeral=True,
                )
                await self._end_auction(auction)
            else:
                await interaction.followup.send(
                    f"✅ Your bid of **{amount:,}** coins has been placed!",
                    ephemeral=True,
                )
                await self._update_embed(auction)

            if prev_bidder_id and prev_bidder_id != interaction.user.id:
                try:
                    await auction.fetch_related("ball")
                    ball_name = auction.ball.country
                except Exception:
                    ball_name = "an item"
                try:
                    prev_user = self.bot.get_user(prev_bidder_id)
                    if not prev_user:
                        prev_user = await self.bot.fetch_user(prev_bidder_id)
                    await prev_user.send(
                        f"⚠️ You have been outbid on the auction for **{ball_name}**!\n"
                        f"New highest bid: **{amount:,}** coins\n"
                        f"Your **{prev_bid_amount:,}** coins have been refunded."
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass
