from tortoise import fields
from tortoise.models import Model


class CollectorCard(Model):
    """
    A collector tier (e.g. Bronze, Silver, Gold).
    Admins create these via the Django admin panel and link a Special background.
    """

    name = fields.CharField(max_length=100)
    description = fields.TextField(default="")
    emoji = fields.CharField(max_length=50, null=True)
    special: fields.ForeignKeyRelation | None = fields.ForeignKeyField(
        "models.Special",
        null=True,
        on_delete=fields.SET_NULL,
        related_name="collector_cards",
        description="Special background awarded with this tier",
    )
    enabled = fields.BooleanField(default=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "collector_card"

    def __str__(self) -> str:
        return self.name


class CollectorRequirement(Model):
    """
    Per-ball threshold for a collector tier.
    e.g. Bronze requires 50 LeBrons, Silver requires 150 LeBrons.
    """

    card: fields.ForeignKeyRelation[CollectorCard] = fields.ForeignKeyField(
        "models.CollectorCard",
        related_name="requirements",
        on_delete=fields.CASCADE,
    )
    ball: fields.ForeignKeyRelation = fields.ForeignKeyField(
        "models.Ball",
        related_name="collector_requirements",
        on_delete=fields.CASCADE,
    )
    count = fields.IntField(
        description="How many of this ball the player must own to claim this tier"
    )

    class Meta:
        table = "collector_requirement"
        unique_together = [("card", "ball")]

    def __str__(self) -> str:
        return f"{self.card_id} — {self.ball_id} × {self.count:,}"


class PlayerCollectorCard(Model):
    """
    Records a player claiming a collector tier for a specific ball.
    ball_instance holds the awarded card that appears in their collection.
    """

    player: fields.ForeignKeyRelation = fields.ForeignKeyField(
        "models.Player",
        related_name="collector_cards",
        on_delete=fields.CASCADE,
    )
    card: fields.ForeignKeyRelation[CollectorCard] = fields.ForeignKeyField(
        "models.CollectorCard",
        related_name="holders",
        on_delete=fields.CASCADE,
    )
    ball: fields.ForeignKeyRelation = fields.ForeignKeyField(
        "models.Ball",
        related_name="collector_claims",
        on_delete=fields.CASCADE,
    )
    ball_instance: fields.OneToOneRelation | None = fields.OneToOneField(
        "models.BallInstance",
        null=True,
        related_name="collector_claim",
        on_delete=fields.SET_NULL,
    )
    claimed_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "collector_playercard"
        unique_together = [("player", "card", "ball")]

    def __str__(self) -> str:
        return f"player#{self.player_id} — {self.card_id} ({self.ball_id})"
