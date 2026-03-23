from django.db import models

from bd_models.models import Player, BallInstance


class Bet(models.Model):
    id: int
    player1 = models.ForeignKey(
        Player, related_name="bets_initiated", on_delete=models.CASCADE
    )
    player2 = models.ForeignKey(
        Player, related_name="bets_received", on_delete=models.CASCADE
    )
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, default=None)
    winner = models.ForeignKey(
        Player, related_name="bets_won", null=True, default=None, on_delete=models.SET_NULL
    )
    cancelled = models.BooleanField(default=False)
    betstakes: models.QuerySet["BetStake"]

    def __str__(self) -> str:
        return str(self.pk)


class BetStake(models.Model):
    id: int
    bet = models.ForeignKey(
        Bet, related_name="betstakes", on_delete=models.CASCADE
    )
    player = models.ForeignKey(
        Player, related_name="betstakes", on_delete=models.CASCADE
    )
    ballinstance = models.ForeignKey(
        BallInstance, related_name="betstakes", on_delete=models.CASCADE
    )

    def __str__(self) -> str:
        return str(self.pk)


class BetHistory(models.Model):
    id: int
    player1_id = models.BigIntegerField()
    player2_id = models.BigIntegerField()
    winner_id = models.BigIntegerField(null=True, default=None)
    bet_date = models.DateTimeField(auto_now_add=True)
    player1_count = models.IntegerField(default=0)
    player2_count = models.IntegerField(default=0)
    cancelled = models.BooleanField(default=False)

    def __str__(self) -> str:
        return str(self.pk)
