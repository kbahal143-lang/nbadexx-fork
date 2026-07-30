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


class MatchResult(models.Model):
    """Records every completed battle match for stats and daily reward tracking."""

    challenger_discord_id = models.BigIntegerField()
    challenged_discord_id = models.BigIntegerField()
    winner_discord_id = models.BigIntegerField()
    winner_score = models.IntegerField()
    loser_score = models.IntegerField()
    played_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "battle_matchresult"
        verbose_name = "Match Result"
        verbose_name_plural = "Match Results"
        ordering = ["-played_at"]

    def __str__(self):
        return f"Match @ {self.played_at:%Y-%m-%d %H:%M} | Winner: {self.winner_discord_id}"


class BattleProfile(models.Model):
    """All-time battle stats per Discord user."""

    discord_id = models.BigIntegerField(unique=True)
    wins = models.IntegerField(default=0)
    losses = models.IntegerField(default=0)
    current_streak = models.IntegerField(default=0)

    class Meta:
        db_table = "battle_profile"
        verbose_name = "Battle Profile"
        verbose_name_plural = "Battle Profiles"
        ordering = ["-wins"]

    def __str__(self):
        return f"Profile {self.discord_id}  W{self.wins}/L{self.losses}"


class BattleCardStats(models.Model):
    """Cumulative points scored per specific card instance per Discord user.

    Stats travel with the card on trade; deleted on quicksell/deletion.
    """

    discord_id = models.BigIntegerField()
    instance_id = models.BigIntegerField()
    total_pts = models.IntegerField(default=0)

    class Meta:
        db_table = "battle_card_stats"
        verbose_name = "Battle Card Stats"
        verbose_name_plural = "Battle Card Stats"
        ordering = ["-total_pts"]
        unique_together = [("discord_id", "instance_id")]

    def __str__(self):
        return f"User {self.discord_id}  Instance {self.instance_id}  {self.total_pts} pts"


class BattleShowcase(models.Model):
    """The card pinned to a user's /profile as their showcase."""

    discord_id = models.BigIntegerField(unique=True)
    instance_id = models.BigIntegerField()   # exact BallInstance pk the user chose
    art_type = models.CharField(max_length=10, default="card")

    class Meta:
        db_table = "battle_showcase"
        verbose_name = "Battle Showcase"
        verbose_name_plural = "Battle Showcases"

    def __str__(self):
        return f"Showcase {self.discord_id}  Instance {self.instance_id}  ({self.art_type})"
