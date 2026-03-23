from tortoise import models, fields

from ballsdex.core.models import Player, BallInstance


class Bet(models.Model):
    id: int
    player1: fields.ForeignKeyRelation[Player] = fields.ForeignKeyField(
        "models.Player", related_name="bets_initiated", on_delete="CASCADE"
    )
    player2: fields.ForeignKeyRelation[Player] = fields.ForeignKeyField(
        "models.Player", related_name="bets_received", on_delete="CASCADE"
    )
    started_at = fields.DatetimeField(auto_now_add=True)
    ended_at = fields.DatetimeField(null=True, default=None)
    winner: fields.ForeignKeyRelation[Player] | None = fields.ForeignKeyField(
        "models.Player", related_name="bets_won", null=True, default=None, on_delete=fields.SET_NULL
    )
    cancelled = fields.BooleanField(default=False)
    betstakes: fields.ReverseRelation["BetStake"]

    def __str__(self) -> str:
        return str(self.pk)

    class Meta:
        table = "betting_bet"


class BetStake(models.Model):
    id: int
    bet: fields.ForeignKeyRelation[Bet] = fields.ForeignKeyField(
        "models.Bet", related_name="betstakes", on_delete=fields.CASCADE
    )
    player: fields.ForeignKeyRelation[Player] = fields.ForeignKeyField(
        "models.Player", related_name="betstakes", on_delete=fields.CASCADE
    )
    ballinstance: fields.ForeignKeyRelation[BallInstance] = fields.ForeignKeyField(
        "models.BallInstance", related_name="betstakes", on_delete=fields.CASCADE
    )

    def __str__(self) -> str:
        return str(self.pk)

    class Meta:
        table = "betting_betstake"


class BetHistory(models.Model):
    id: int
    player1_id = fields.BigIntField()
    player2_id = fields.BigIntField()
    winner_id = fields.BigIntField(null=True, default=None)
    bet_date = fields.DatetimeField(auto_now_add=True)
    player1_count = fields.IntField(default=0)
    player2_count = fields.IntField(default=0)
    cancelled = fields.BooleanField(default=False)

    def __str__(self) -> str:
        return str(self.pk)

    class Meta:
        table = "betting_bethistory"
