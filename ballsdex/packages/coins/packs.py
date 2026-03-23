
import logging
import random
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands
from tortoise import timezone
from tortoise.transactions import in_transaction

from ballsdex.core.models import (
    Ball,
    BallInstance,
    Player
)
from ballsdex.settings import settings

from .views import ConfirmView
from .coins import _active_operations
from .models import Pack, PackOpenHistory, PlayerPack, PlayerMoney
from .transformers import PackTransform, OwnedPackTransform

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.coins")


class Packs(commands.GroupCog, group_name="pack"):
    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot

    @app_commands.command()
    async def list(self, interaction: discord.Interaction):
        """
        View all available packs you can buy.
        """
        packs = await Pack.filter(enabled=True).order_by("price").prefetch_related("special")
        
        if not packs:
            await interaction.response.send_message(
                "No packs are currently available!",
                ephemeral=True
            )
            return
        
        embed = discord.Embed(
            title="Available Packs",
            description=f"Here are the packs you can buy with coins:",
            color=discord.Color.blue()
        )
        
        for pack in packs:
            emoji = pack.emoji + " " if pack.emoji else ""
            description = pack.description if pack.description else "No description"
            limit_text = f"\nDaily Limit: {pack.daily_limit}" if pack.daily_limit > 0 else ""
            
            embed.add_field(
                name=f"{emoji}{pack.name}",
                value=(
                    f"Price: **{pack.price:,}** coins\n"
                    f"{description}{limit_text}"
                ),
                inline=True
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command()
    async def buy(
        self,
        interaction: discord.Interaction,
        pack: PackTransform,
        amount: int = 1,
    ):
        """
        Buy packs with your coins.

        Parameters
        ----------
        pack: Pack
            The pack you want to buy
        amount: int
            Number of packs to buy (default: 1)
        """
        if amount < 1:
            await interaction.response.send_message("Amount must be at least 1!", ephemeral=True)
            return
        
        if amount > 100:
            await interaction.response.send_message("You can only buy up to 100 packs at a time!", ephemeral=True)
            return
        
        if interaction.user.id in _active_operations:
            await interaction.response.send_message("You have another operation in progress!", ephemeral=True)
            return
        
        _active_operations.add(interaction.user.id)
        try:
            total_cost = pack.price * amount
            
            player, _ = await Player.get_or_create(discord_id=interaction.user.id)
            money, _ = await PlayerMoney.get_or_create(player=player)
            
            if money.coins < total_cost:
                await interaction.response.send_message(
                    f"You don't have enough coins! You need **{total_cost:,}** coins but only have **{money.coins:,}** coins.",
                    ephemeral=True
                )
                return
            
            emoji = pack.emoji + " " if pack.emoji else ""
            
            embed = discord.Embed(
                title="Confirm Purchase",
                description=(
                    f"Are you sure you want to buy **{amount}x {emoji}{pack.name}** "
                    f"for **{total_cost:,}** coins?"
                ),
                color=discord.Color.blue()
            )
            
            view = ConfirmView(interaction.user)
            await interaction.response.send_message(embed=embed, view=view)
            
            await view.wait()
            
            if view.value is None:
                embed.description = "Purchase timed out."
                embed.color = discord.Color.greyple()
                await interaction.edit_original_response(embed=embed, view=None)
                return
            
            if not view.value:
                embed.description = "Purchase cancelled."
                embed.color = discord.Color.red()
                await interaction.edit_original_response(embed=embed, view=None)
                return
            
            async with in_transaction():
                await player.refresh_from_db()
                await money.refresh_from_db()
                
                if money.coins < total_cost:
                    embed.description = "You no longer have enough coins!"
                    embed.color = discord.Color.red()
                    await interaction.edit_original_response(embed=embed, view=None)
                    return
                
                money.coins -= total_cost
                await money.save(update_fields=["coins"])
                
                player_pack, created = await PlayerPack.get_or_create(
                    player=player,
                    pack=pack,
                    defaults={"quantity": 0}
                )
                player_pack.quantity += amount
                await player_pack.save(update_fields=["quantity"])
            
            embed.title = "Purchase Complete!"
            embed.description = (
                f"You bought **{amount}x {emoji}{pack.name}**!\n"
                f"Coins spent: **{total_cost:,}**\n"
                f"New balance: **{money.coins:,}** coins\n"
                f"You now have **{player_pack.quantity}** of this pack."
            )
            embed.color = discord.Color.green()
            await interaction.edit_original_response(embed=embed, view=None)
        finally:
            _active_operations.discard(interaction.user.id)

    @app_commands.command()
    async def inventory(self, interaction: discord.Interaction):
        """
        View your owned packs.
        """
        player, _ = await Player.get_or_create(discord_id=interaction.user.id)
        player_packs = await PlayerPack.filter(player=player, quantity__gt=0).prefetch_related("pack")
        
        if not player_packs:
            await interaction.response.send_message(
                "You don't own any packs! Use `/pack buy` to purchase some.",
                ephemeral=True
            )
            return
        
        embed = discord.Embed(
            title="Your Packs",
            description="",
            color=discord.Color.gold()
        )
        
        for pp in player_packs:
            emoji = pp.pack.emoji + " " if pp.pack.emoji else ""
            embed.description += f"{emoji}**{pp.pack.name}**: {pp.quantity}\n"
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command()
    async def give(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        pack: OwnedPackTransform,
        amount: int = 1,
    ):
        """
        Give packs to another user.

        Parameters
        ----------
        user: discord.User
            The user you want to give packs to
        pack: PlayerPack
            The pack you want to give
        amount: int
            Number of packs to give (default: 1)
        """
        if user.id == interaction.user.id:
            await interaction.response.send_message("You cannot give packs to yourself!", ephemeral=True)
            return
        
        if user.bot:
            await interaction.response.send_message("You cannot give packs to bots!", ephemeral=True)
            return
        
        if amount < 1:
            await interaction.response.send_message("Amount must be at least 1!", ephemeral=True)
            return
        
        if amount > pack.quantity:
            await interaction.response.send_message(
                f"You only have **{pack.quantity}** of this pack!",
                ephemeral=True
            )
            return
        
        if interaction.user.id in _active_operations:
            await interaction.response.send_message("You have another operation in progress!", ephemeral=True)
            return
        
        await pack.fetch_related("pack", "player")
        the_pack = pack.pack
        
        _active_operations.add(interaction.user.id)
        try:
            async with in_transaction():
                await pack.refresh_from_db()
                
                if pack.quantity < amount:
                    await interaction.response.send_message(
                        f"You no longer have enough packs!",
                        ephemeral=True
                    )
                    return
                
                pack.quantity -= amount
                await pack.save(update_fields=["quantity"])
                
                recipient, _ = await Player.get_or_create(discord_id=user.id)
                
                recipient_pack = await PlayerPack.filter(player=recipient, pack=the_pack).first()
                if recipient_pack:
                    recipient_pack.quantity += amount
                    await recipient_pack.save(update_fields=["quantity"])
                else:
                    await PlayerPack.create(
                        player=recipient,
                        pack=the_pack,
                        quantity=amount
                    )
            
            emoji = the_pack.emoji + " " if the_pack.emoji else ""
            await interaction.response.send_message(
                f"{interaction.user.mention} gave **{amount}x {emoji}{the_pack.name}** to {user.mention}!\n"
                f"You now have **{pack.quantity}** of this pack."
            )
        finally:
            _active_operations.discard(interaction.user.id)

    @app_commands.command()
    async def open(
        self,
        interaction: discord.Interaction,
        pack: OwnedPackTransform,
        amount: int = 1,
    ):
        """
        Open your owned packs to get NBAs.

        Parameters
        ----------
        pack: PlayerPack
            The pack you want to open
        amount: int
            Number of packs to open (default: 1)
        """
        if amount < 1:
            await interaction.response.send_message("Amount must be at least 1!", ephemeral=True)
            return
        
        if amount > 10:
            await interaction.response.send_message(
                "You can only open up to 10 packs at a time!",
                ephemeral=True
            )
            return
        
        if interaction.user.id in _active_operations:
            await interaction.response.send_message(
                "You have another pack operation in progress! Please wait.",
                ephemeral=True
            )
            return
        
        await interaction.response.defer()
        
        _active_operations.add(interaction.user.id)
        try:
            await pack.fetch_related("pack", "pack__special", "player")
            the_pack = pack.pack
            player = pack.player
            
            async with in_transaction():
                await pack.refresh_from_db()
                
                if pack.quantity < amount:
                    await interaction.followup.send(
                        f"You only have **{pack.quantity}** of this pack!"
                    )
                    return
                
                if the_pack.daily_limit > 0:
                    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
                    opens_today = await PackOpenHistory.filter(
                        player=player,
                        pack=the_pack,
                        opened_at__gte=today_start
                    ).count()
                    
                    remaining = the_pack.daily_limit - opens_today
                    if remaining <= 0:
                        hours_until_reset = 24 - timezone.now().hour
                        await interaction.followup.send(
                            f"You've reached the daily limit for opening **{the_pack.name}**!\n"
                            f"Your limit will reset in about {hours_until_reset} hours."
                        )
                        return
                    
                    if amount > remaining:
                        await interaction.followup.send(
                            f"You can only open **{remaining}** more of this pack today!"
                        )
                        return
                
                pack.quantity -= amount
                await pack.save(update_fields=["quantity"])
                
                special_to_use = None
                if the_pack.special_id:
                    special_to_use = the_pack.special
                
                if the_pack.special_only and special_to_use:
                    special_balls = await BallInstance.filter(
                        special=special_to_use,
                        deleted=False
                    ).prefetch_related("ball").distinct().values_list("ball_id", flat=True)
                    
                    available_balls = await Ball.filter(
                        enabled=True,
                        packable=True,
                        id__in=list(special_balls),
                        rarity__gte=the_pack.min_rarity,
                        rarity__lte=the_pack.max_rarity
                    ).all()
                    
                    if not available_balls:
                        available_balls = await Ball.filter(
                            enabled=True,
                            packable=True,
                            rarity__gte=the_pack.min_rarity,
                            rarity__lte=the_pack.max_rarity
                        ).all()
                else:
                    available_balls = await Ball.filter(
                        enabled=True,
                        packable=True,
                        rarity__gte=the_pack.min_rarity,
                        rarity__lte=the_pack.max_rarity
                    ).all()
                
                if not available_balls:
                    pack.quantity += amount
                    await pack.save(update_fields=["quantity"])
                    await interaction.followup.send(
                        f"No {settings.plural_collectible_name} available in this pack's rarity range!"
                    )
                    return
                
                total_rarity = sum(b.rarity for b in available_balls)
                
                results = []
                
                for _ in range(amount):
                    pack_cards = []
                    for _ in range(the_pack.cards_count):
                        roll = random.uniform(0, total_rarity)
                        cumulative = 0
                        selected_ball = available_balls[0]
                        
                        for ball in available_balls:
                            cumulative += ball.rarity
                            if roll <= cumulative:
                                selected_ball = ball
                                break
                        
                        attack_bonus = random.randint(-settings.max_attack_bonus, settings.max_attack_bonus)
                        health_bonus = random.randint(-settings.max_health_bonus, settings.max_health_bonus)
                        
                        instance = await BallInstance.create(
                            ball=selected_ball,
                            player=player,
                            attack_bonus=attack_bonus,
                            health_bonus=health_bonus,
                            special=special_to_use,
                            server_id=interaction.guild_id if interaction.guild else None,
                        )
                        pack_cards.append(instance)
                        results.append(instance)
                    
                    await PackOpenHistory.create(
                        player=player,
                        pack=the_pack,
                        ball_received=pack_cards[0] if pack_cards else None
                    )
            
            emoji = the_pack.emoji + " " if the_pack.emoji else ""
            
            if len(results) == 1:
                inst = results[0]
                ball = inst.countryball
                attack = "{:+}".format(inst.attack_bonus)
                health = "{:+}".format(inst.health_bonus)
                special_text = f" ({inst.specialcard.name})" if inst.specialcard else ""
                
                embed = discord.Embed(
                    title=f"{emoji}{the_pack.name}",
                    description=(
                        f"{interaction.user.mention} You packed **{ball.country}**!{special_text}\n"
                        f"(#{inst.pk:0X}, {attack}%/{health}%)"
                    ),
                    color=discord.Color.gold()
                )
                
                ball_emoji = self.bot.get_emoji(ball.emoji_id)
                if ball_emoji:
                    embed.set_thumbnail(url=ball_emoji.url)
            else:
                description = f"{interaction.user.mention} You opened **{amount}x {the_pack.name}**!\n\n"
                for inst in results:
                    ball = inst.countryball
                    attack = "{:+}".format(inst.attack_bonus)
                    health = "{:+}".format(inst.health_bonus)
                    special_text = f" ({inst.specialcard.name})" if inst.specialcard else ""
                    ball_emoji = self.bot.get_emoji(ball.emoji_id)
                    emoji_str = str(ball_emoji) + " " if ball_emoji else ""
                    description += f"{emoji_str}**{ball.country}**{special_text} (#{inst.pk:0X}, {attack}%/{health}%)\n"
                
                embed = discord.Embed(
                    title=f"{emoji}{the_pack.name} Results",
                    description=description,
                    color=discord.Color.gold()
                )
            
            await interaction.followup.send(embed=embed)
        finally:
            _active_operations.discard(interaction.user.id)
