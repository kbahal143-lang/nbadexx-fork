import discord
from discord import app_commands

from ballsdex.core.models import Player

from .models import Pack, PlayerPack


class PackTransformer(app_commands.Transformer):
    async def transform(self, interaction: discord.Interaction, value: str) -> Pack:
        try:
            pack = await Pack.get(id=int(value))
        except Exception:
            pack = await Pack.filter(name__icontains=value).first()
        if not pack:
            raise app_commands.TransformerError(value, type(value), self)
        return pack

    async def autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        try:
            packs = await Pack.filter(enabled=True).order_by("price")
            choices = []
            for pack in packs:
                if current.lower() in pack.name.lower():
                    emoji = pack.emoji + " " if pack.emoji else ""
                    choices.append(app_commands.Choice(
                        name=f"{emoji}{pack.name} - {pack.price:,} coins",
                        value=str(pack.id)
                    ))
            return choices[:25]
        except Exception:
            return []


class OwnedPackTransformer(app_commands.Transformer):
    async def transform(self, interaction: discord.Interaction, value: str) -> PlayerPack:
        player, _ = await Player.get_or_create(discord_id=interaction.user.id)
        try:
            player_pack = await PlayerPack.get(id=int(value), player=player)
        except Exception:
            player_pack = await PlayerPack.filter(
                player=player, pack__name__icontains=value, quantity__gt=0
            ).first()
        if not player_pack or player_pack.quantity <= 0:
            raise app_commands.TransformerError(value, type(value), self)
        return player_pack

    async def autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        try:
            player, _ = await Player.get_or_create(discord_id=interaction.user.id)
            player_packs = await PlayerPack.filter(player=player, quantity__gt=0).prefetch_related("pack")
            choices = []
            for pp in player_packs:
                if current.lower() in pp.pack.name.lower():
                    emoji = pp.pack.emoji + " " if pp.pack.emoji else ""
                    choices.append(app_commands.Choice(
                        name=f"{emoji}{pp.pack.name} x{pp.quantity}",
                        value=str(pp.id)
                    ))
            return choices[:25]
        except Exception:
            return []


PackTransform = app_commands.Transform[Pack, PackTransformer]
OwnedPackTransform = app_commands.Transform[PlayerPack, OwnedPackTransformer]
