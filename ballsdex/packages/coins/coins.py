import logging
from typing import TYPE_CHECKING, AsyncIterator, cast

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button
from tortoise.transactions import in_transaction

from ballsdex.core.models import (
    BallInstance,
    Player
)
from ballsdex.core.utils import menus
from ballsdex.core.utils.paginator import Pages
from ballsdex.core.utils.sorting import FilteringChoices, SortingChoices, filter_balls, sort_balls
from ballsdex.core.utils.transformers import BallInstanceTransform, BallEnabledTransform, SpecialEnabledTransform
from ballsdex.settings import settings

from .views import ConfirmView
from .models import BallValue, PlayerMoney

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.coins")
_active_operations: set[int] = set()


class BulkSellSource(menus.ListPageSource):
    def __init__(self, entries: list[int]):
        super().__init__(entries, per_page=25)
        self.cache: dict[int, BallInstance] = {}

    async def prepare(self):
        first_entries = (
            self.entries[: self.per_page * 5]
            if len(self.entries) > self.per_page * 5
            else self.entries
        )
        balls = await BallInstance.filter(id__in=first_entries).prefetch_related("ball", "special")
        for ball in balls:
            self.cache[ball.pk] = ball

    async def fetch_page(self, ball_ids: list[int]) -> AsyncIterator[BallInstance]:
        if ball_ids and ball_ids[0] not in self.cache:
            async for ball in BallInstance.filter(id__in=ball_ids).prefetch_related("ball", "special"):
                self.cache[ball.pk] = ball
        for id in ball_ids:
            if id in self.cache:
                yield self.cache[id]

    async def format_page(self, menu: "BulkSellSelector", ball_ids: list[int]):
        await menu.set_options(self.fetch_page(ball_ids))
        return True


class BulkSellSelector(Pages):
    def __init__(
        self,
        interaction: discord.Interaction["BallsDexBot"],
        balls: list[int],
    ):
        self.bot = interaction.client
        self.interaction = interaction
        source = BulkSellSource(balls)
        super().__init__(source, interaction=interaction)
        self.source: BulkSellSource = source
        self.add_item(self.select_ball_menu)
        self.add_item(self.confirm_button)
        self.add_item(self.select_all_button)
        self.add_item(self.clear_button)
        self.balls_selected: set[int] = set()
        self.confirmed = False

    async def set_options(self, balls: AsyncIterator[BallInstance]):
        options: list[discord.SelectOption] = []
        async for ball in balls:
            if ball.favorite or ball.deleted:
                continue
            emoji = self.bot.get_emoji(int(ball.countryball.emoji_id))
            special = ball.special_emoji(self.bot, True)
            ballvalue = await BallValue.get_or_none(ball=ball.countryball)
            value = ballvalue.quicksell_value if ballvalue else 100
            if ball.specialcard:
                value = int(value * 1.5)
            options.append(
                discord.SelectOption(
                    label=f"{special}#{ball.pk:0X} {ball.countryball.country}",
                    description=f"ATK: {ball.attack_bonus:+d}% • HP: {ball.health_bonus:+d}% • {value:,} coins",
                    emoji=emoji,
                    value=f"{ball.pk}",
                    default=ball.pk in self.balls_selected,
                )
            )
        if options:
            self.select_ball_menu.options = options
            self.select_ball_menu.max_values = len(options)
            self.select_ball_menu.min_values = 0
            self.select_ball_menu.disabled = False
        else:
            self.select_ball_menu.options = [
                discord.SelectOption(label="No NBAs available", value="none")
            ]
            self.select_ball_menu.max_values = 1
            self.select_ball_menu.min_values = 1
            self.select_ball_menu.disabled = True

    @discord.ui.select(min_values=1, max_values=25)
    async def select_ball_menu(
        self, interaction: discord.Interaction["BallsDexBot"], item: discord.ui.Select
    ):
        await interaction.response.defer()
        for value in item.values:
            if value == "none":
                continue
            ball_id = int(value)
            if ball_id in self.source.cache:
                self.balls_selected.add(ball_id)
            else:
                ball_instance = await BallInstance.get(id=ball_id).prefetch_related("ball", "special")
                self.source.cache[ball_id] = ball_instance
                self.balls_selected.add(ball_id)

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.primary)
    async def confirm_button(
        self, interaction: discord.Interaction["BallsDexBot"], button: Button
    ):
        await interaction.response.defer()
        if len(self.balls_selected) == 0:
            await interaction.followup.send(
                f"You have not selected any {settings.plural_collectible_name} to sell.",
                ephemeral=True,
            )
            return
        self.confirmed = True
        self.stop()

    @discord.ui.button(label="Select Page", style=discord.ButtonStyle.secondary)
    async def select_all_button(
        self, interaction: discord.Interaction["BallsDexBot"], button: Button
    ):
        await interaction.response.defer(thinking=True, ephemeral=True)
        for opt in self.select_ball_menu.options:
            if opt.value == "none":
                continue
            ball_id = int(opt.value)
            self.balls_selected.add(ball_id)
        await interaction.followup.send(
            f"All {settings.plural_collectible_name} on this page have been selected.\n"
            "Note that the menu may not reflect this change until you change page.",
            ephemeral=True,
        )

    @discord.ui.button(label="Clear", style=discord.ButtonStyle.danger)
    async def clear_button(
        self, interaction: discord.Interaction["BallsDexBot"], button: Button
    ):
        await interaction.response.defer(thinking=True, ephemeral=True)
        self.balls_selected.clear()
        await interaction.followup.send(
            f"You have cleared all currently selected {settings.plural_collectible_name}.\n"
            "There may be an instance where it shows selected items on the current page, "
            "this is not the case - changing page will show the correct state.",
            ephemeral=True,
        )


class Coins(commands.GroupCog, group_name="coins"):
    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot

    @app_commands.command()
    async def balance(self, interaction: discord.Interaction):
        """
        Check your coins balance.
        """
        player, _ = await Player.get_or_create(discord_id=interaction.user.id)
        money, _ = await PlayerMoney.get_or_create(player=player)
        
        embed = discord.Embed(
            title="Coins Balance",
            description=f"{interaction.user.mention} has **{money.coins:,}** coins",
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command()
    async def leaderboard(self, interaction: discord.Interaction):
        """
        View the top 10 users with the most coins.
        """
        await interaction.response.defer()
        
        top_players = await PlayerMoney.filter(coins__gt=0).order_by("-coins").limit(10).prefetch_related("player")
        
        if not top_players:
            await interaction.followup.send("No players with coins found!")
            return
        
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        
        for i, player in enumerate(top_players):
            try:
                user = await self.bot.fetch_user(player.player.discord_id)
                username = user.display_name
            except Exception:
                username = f"Unknown User"
            
            if i < 3:
                lines.append(f"{medals[i]} **{username}** — `{player.coins:,}` coins")
            else:
                lines.append(f"`#{i+1}` {username} — `{player.coins:,}` coins")
        
        embed = discord.Embed(
            title="💰 Richest Players",
            description="\n".join(lines),
            color=discord.Color.gold()
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command()
    async def give(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        amount: int,
    ):
        """
        Give coins to another user.

        Parameters
        ----------
        user: discord.User
            The user you want to give coins to
        amount: int
            Number of coins to give
        """
        if user.id == interaction.user.id:
            await interaction.response.send_message("You cannot give coins to yourself!", ephemeral=True)
            return
        
        if user.bot:
            await interaction.response.send_message("You cannot give coins to bots!", ephemeral=True)
            return
        
        if amount < 1:
            await interaction.response.send_message("Amount must be at least 1!", ephemeral=True)
            return
        
        if interaction.user.id in _active_operations:
            await interaction.response.send_message("You have another operation in progress!", ephemeral=True)
            return
        
        if user.id in _active_operations:
            await interaction.response.send_message("That user has another operation in progress!", ephemeral=True)
            return
        
        _active_operations.add(interaction.user.id)
        try:
            async with in_transaction():
                player, _ = await Player.get_or_create(discord_id=interaction.user.id)
                money, _ = await PlayerMoney.get_or_create(player=player)
                
                if money.coins < amount:
                    await interaction.response.send_message(
                        f"You don't have enough coins! You have **{money.coins:,}** coins.",
                        ephemeral=True
                    )
                    return
                
                recipient, _ = await Player.get_or_create(discord_id=user.id)
                recipient_money, _ = await PlayerMoney.get_or_create(player=recipient)
                
                money.coins -= amount
                recipient_money.coins += amount
                await money.save(update_fields=["coins"])
                await recipient_money.save(update_fields=["coins"])
            
            await interaction.response.send_message(
                f"{interaction.user.mention} gave **{amount:,}** coins to {user.mention}!\n"
                f"New balance: **{money.coins:,}** coins"
            )
        finally:
            _active_operations.discard(interaction.user.id)

    @app_commands.command()
    async def sell(
        self,
        interaction: discord.Interaction,
        countryball: BallInstanceTransform,
    ):
        """
        Sell an NBA for coins (quicksell).

        Parameters
        ----------
        countryball: BallInstance
            The NBA you want to sell
        """
        if countryball.favorite:
            await interaction.response.send_message(
                f"You cannot sell a favorited {settings.collectible_name}!",
                ephemeral=True
            )
            return

        if not countryball.is_tradeable:
            await interaction.response.send_message(
                f"This {settings.collectible_name} cannot be sold!",
                ephemeral=True
            )
            return

        if await countryball.is_locked():
            await interaction.response.send_message(
                f"This {settings.collectible_name} is currently locked in a trade or bet and cannot be sold!",
                ephemeral=True
            )
            return

        if interaction.user.id in _active_operations:
            await interaction.response.send_message("You have another operation in progress!", ephemeral=True)
            return

        _active_operations.add(interaction.user.id)
        try:
            await countryball.lock_for_trade()
            
            ball = countryball.countryball
            ballvalue = await BallValue.get_or_none(ball=ball)
            sell_value = ballvalue.quicksell_value if ballvalue else 100
            
            bonus_multiplier = 1.0
            if countryball.specialcard:
                bonus_multiplier = 1.5
            
            final_value = int(sell_value * bonus_multiplier)
            
            attack = "{:+}".format(countryball.attack_bonus)
            health = "{:+}".format(countryball.health_bonus)
            special_text = f" ({countryball.specialcard.name})" if countryball.specialcard else ""
            
            embed = discord.Embed(
                title="Confirm Quicksell",
                description=(
                    f"Are you sure you want to sell **#{countryball.pk:0X} {ball.country}{special_text}** "
                    f"({attack}%/{health}%) for **{final_value:,}** coins?"
                ),
                color=discord.Color.orange()
            )
            
            view = ConfirmView(interaction.user)
            await interaction.response.send_message(embed=embed, view=view)
            
            await view.wait()
            
            if view.value is None:
                await countryball.unlock()
                embed.description = "Quicksell timed out."
                embed.color = discord.Color.greyple()
                await interaction.edit_original_response(embed=embed, view=None)
                return
            
            if not view.value:
                await countryball.unlock()
                embed.description = "Quicksell cancelled."
                embed.color = discord.Color.red()
                await interaction.edit_original_response(embed=embed, view=None)
                return
            
            async with in_transaction():
                player = await Player.get(discord_id=interaction.user.id)
                money, _ = await PlayerMoney.get_or_create(player=player)
                await countryball.refresh_from_db()
                
                if countryball.player_id != player.pk or countryball.deleted:
                    await countryball.unlock()
                    embed.description = f"You no longer own this {settings.collectible_name}!"
                    embed.color = discord.Color.red()
                    await interaction.edit_original_response(embed=embed, view=None)
                    return
                
                countryball.deleted = True
                await countryball.save(update_fields=["deleted"])
                await countryball.unlock()
                
                money.coins += final_value
                await money.save(update_fields=["coins"])
            
            embed.title = "Quicksell Complete!"
            embed.description = (
                f"You sold **#{countryball.pk:0X} {ball.country}{special_text}** for **{final_value:,}** coins!\n"
                f"New balance: **{money.coins:,}** coins"
            )
            embed.color = discord.Color.green()
            await interaction.edit_original_response(embed=embed, view=None)
        except Exception:
            try:
                await countryball.unlock()
            except Exception:
                pass
            raise
        finally:
            _active_operations.discard(interaction.user.id)

    @app_commands.command()
    async def bulk_sell(
        self,
        interaction: discord.Interaction["BallsDexBot"],
        countryball: BallEnabledTransform | None = None,
        sort: SortingChoices | None = None,
        special: SpecialEnabledTransform | None = None,
        filter: FilteringChoices | None = None,
    ):
        """
        Bulk sell nbas for coins, with paramaters to aid with searching.

        Parameters
        ----------
        countryball: Ball
            The nba you would like to filter the results to
        sort: SortingChoices
            Choose how nbas are sorted. Can be used to show duplicates.
        special: Special
            Filter the results to a special event
        filter: FilteringChoices
            Filter the results to a specific filter
        """
        if interaction.user.id in _active_operations:
            await interaction.response.send_message("You have another operation in progress!", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        player, _ = await Player.get_or_create(discord_id=interaction.user.id)
        money, _ = await PlayerMoney.get_or_create(player=player)
        
        query = BallInstance.filter(
            player=player, favorite=False, tradeable=True, deleted=False, locked__isnull=True
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
        
        view = BulkSellSelector(interaction, balls)
        await view.start(
            content=f"Select the {settings.plural_collectible_name} you want to sell, "
            "note that the display will wipe on pagination however "
            f"the selected {settings.plural_collectible_name} will remain."
        )
        
        await view.wait()
        
        if not view.confirmed or not view.balls_selected:
            return
        
        if interaction.user.id in _active_operations:
            await interaction.edit_original_response(
                content="You have another operation in progress!", embed=None, view=None
            )
            return
        
        _active_operations.add(interaction.user.id)
        locked_balls: list[BallInstance] = []
        try:
            valid_balls = await BallInstance.filter(
                id__in=list(view.balls_selected),
                player=player,
                deleted=False,
                favorite=False,
                tradeable=True,
                locked__isnull=True
            ).prefetch_related("ball", "special")
            
            for inst in valid_balls:
                await inst.lock_for_trade()
                locked_balls.append(inst)
            
            if not locked_balls:
                await interaction.edit_original_response(
                    content=None,
                    embed=discord.Embed(
                        title="Bulk Sell Failed",
                        description="None of the selected NBAs could be sold. They may have been traded or locked.",
                        color=discord.Color.red()
                    ),
                    view=None
                )
                return
            
            total_value = 0
            for inst in locked_balls:
                value = inst.countryball.ballvalue.quicksell_value
                if inst.specialcard:
                    value = int(value * 1.5)
                total_value += value
            
            confirm_embed = discord.Embed(
                title="Confirm Bulk Sell",
                description=(
                    f"Are you sure you want to sell **{len(locked_balls)}** "
                    f"{settings.plural_collectible_name} for **{total_value:,}** coins?\n\n"
                    f"This action cannot be undone!"
                ),
                color=discord.Color.orange()
            )
            
            confirm_view = ConfirmView(interaction.user)
            await interaction.edit_original_response(content=None, embed=confirm_embed, view=confirm_view)
            
            await confirm_view.wait()
            
            if confirm_view.value is None or not confirm_view.value:
                for inst in locked_balls:
                    await inst.unlock()
                confirm_embed.title = "Bulk Sell Cancelled"
                confirm_embed.description = "You cancelled the bulk sell."
                confirm_embed.color = discord.Color.red()
                await interaction.edit_original_response(embed=confirm_embed, view=None)
                return
            
            sold_count = 0
            actual_value = 0
            
            async with in_transaction():
                await player.refresh_from_db()
                await money.refresh_from_db()
                
                for inst in locked_balls:
                    await inst.refresh_from_db()
                    if inst.player_id == player.pk and not inst.deleted:
                        value = inst.countryball.ballvalue.quicksell_value
                        if inst.specialcard:
                            value = int(value * 1.5)
                        actual_value += value
                        inst.deleted = True
                        await inst.save(update_fields=["deleted"])
                        sold_count += 1
                    await inst.unlock()
                
                money.coins += actual_value
                await money.save(update_fields=["coins"])
            
            skipped = len(locked_balls) - sold_count
            skip_text = f"\n({skipped} skipped)" if skipped > 0 else ""
            embed = discord.Embed(
                title="Bulk Quicksell Complete!",
                description=(
                    f"You sold **{sold_count}** {settings.plural_collectible_name} for **{actual_value:,}** coins!{skip_text}\n"
                    f"New balance: **{money.coins:,}** coins"
                ),
                color=discord.Color.green()
            )
            await interaction.edit_original_response(embed=embed, view=None)
        except Exception:
            for inst in locked_balls:
                try:
                    await inst.unlock()
                except Exception:
                    pass
            raise
        finally:
            _active_operations.discard(interaction.user.id)
