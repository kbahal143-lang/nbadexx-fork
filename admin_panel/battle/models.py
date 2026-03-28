from django.db import models

from bd_models.models import Ball, Player, BallInstance


class PlayerPosition(models.Model):

    POSITION_CHOICES = [
        ("PG", "Point Guard"),
        ("SG", "Shooting Guard"),
        ("SF", "Small Forward"),
        ("PF", "Power Forward"),
        ("C",  "Center"),
    ]

    ball = models.OneToOneField(
        Ball,
        on_delete=models.CASCADE,
        related_name="basketball_position",
    )
    primary = models.CharField(max_length=2, choices=POSITION_CHOICES)
    secondary = models.CharField(max_length=2, choices=POSITION_CHOICES, blank=True, null=True)

    class Meta:
        db_table = "battle_playerposition"
        verbose_name = "Player Position"
        verbose_name_plural = "Player Positions"
        ordering = ["ball__country"]

    def __str__(self):
        pos = f"{self.primary}/{self.secondary}" if self.secondary else self.primary
        return f"{self.ball.country} — {pos}"


class Team(models.Model):

    player = models.OneToOneField(
        Player,
        on_delete=models.CASCADE,
        related_name="battle_team",
    )
    pg = models.ForeignKey(
        BallInstance, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="team_pg_slot", verbose_name="Point Guard",
    )
    sg = models.ForeignKey(
        BallInstance, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="team_sg_slot", verbose_name="Shooting Guard",
    )
    sf = models.ForeignKey(
        BallInstance, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="team_sf_slot", verbose_name="Small Forward",
    )
    pf = models.ForeignKey(
        BallInstance, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="team_pf_slot", verbose_name="Power Forward",
    )
    c = models.ForeignKey(
        BallInstance, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="team_c_slot", verbose_name="Center",
    )

    class Meta:
        db_table = "battle_team"
        verbose_name = "Team"
        verbose_name_plural = "Teams"

    def __str__(self):
        return f"Team of player #{self.player_id}"

    def is_complete(self) -> bool:
        return all([self.pg_id, self.sg_id, self.sf_id, self.pf_id, self.c_id])
