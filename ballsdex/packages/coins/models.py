from tortoise import models, fields
from tortoise.contrib.postgres.indexes import PostgreSQLIndex

from ballsdex.core.models import Special, Player, Ball


class Pack(models.Model):
    id: int
    name = fields.CharField(max_length=64, unique=True, description="Pack name")
    description = fields.TextField(description="Pack description", null=True, default=None)
    emoji = fields.CharField(max_length=64, description="Emoji for this pack", null=True, default=None)
    price = fields.IntField(description="Price in coins to buy this pack")
    cards_count = fields.IntField(description="Number of cards in this pack", default=1)
    min_rarity = fields.FloatField(description="Minimum rarity of balls in this pack", default=0.0)
    max_rarity = fields.FloatField(description="Maximum rarity of balls in this pack", default=100.0)
    special: fields.ForeignKeyRelation[Special] | None = fields.ForeignKeyField(
        "models.Special", null=True, default=None, on_delete=fields.SET_NULL,
        description="Optional: only give balls from this special event"
    )
    special_only = fields.BooleanField(default=False, description="Only include special cards in this pack")
    daily_limit = fields.IntField(description="Maximum packs a player can open per day (0 = unlimited)", default=0)
    enabled = fields.BooleanField(default=True, description="Whether this pack is available for purchase")
    created_at = fields.DatetimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name

    class Meta:
        table = "coins_pack"


class PlayerPack(models.Model):
    id: int
    player: fields.ForeignKeyRelation[Player] = fields.ForeignKeyField(
        "models.Player", related_name="playerpacks", on_delete=fields.CASCADE
    )
    pack: fields.ForeignKeyRelation[Pack] = fields.ForeignKeyField(
        "models.Pack", related_name="playerpacks", on_delete=fields.CASCADE
    )
    quantity = fields.IntField(default=0, description="Number of packs owned")

    def __str__(self) -> str:
        return f"{self.player} - {self.pack} x{self.quantity}"

    class Meta:
        table = "coins_playerpack"
        unique_together = ("player", "pack")
        indexes = [
            PostgreSQLIndex(fields=("player_id",)),
            PostgreSQLIndex(fields=("pack_id",)),
        ]


class PackOpenHistory(models.Model):
    id: int
    player: fields.ForeignKeyRelation[Player] = fields.ForeignKeyField(
        "models.Player", related_name="pack_opens", on_delete=fields.CASCADE
    )
    pack: fields.ForeignKeyRelation[Pack] = fields.ForeignKeyField(
        "models.Pack", related_name="pack_opens", on_delete=fields.CASCADE
    )
    opened_at = fields.DatetimeField(auto_now_add=True)
    cards_received = fields.IntField(description="Number of cards received", default=1)

    def __str__(self) -> str:
        return f"{self.player} opened {self.pack}"

    class Meta:
        table = "coins_packopenhistory"
        indexes = [
            PostgreSQLIndex(fields=("player_id",)),
            PostgreSQLIndex(fields=("pack_id",)),
            PostgreSQLIndex(fields=("opened_at",)),
        ]


class PlayerMoney(models.Model):
    id: int
    player: fields.OneToOneRelation[Player] = fields.OneToOneField("models.Player", on_delete=fields.CASCADE)
    coins = fields.IntField(description="Player coins", default=0)

    class Meta:
        table = "coins_playermoney"
        indexes = [
            PostgreSQLIndex(fields=("player_id",)),
        ]


class BallValue(models.Model):
    id: int
    ball: fields.OneToOneRelation[Ball] = fields.OneToOneField("models.Ball", related_name="ballvalue", on_delete=fields.CASCADE)
    quicksell_value = fields.IntField(description="Coins received when quickselling this ball", default=100)

    class Meta:
        table = "coins_ballvalue"

