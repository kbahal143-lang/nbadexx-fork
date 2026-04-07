from django.db import models

from bd_models.models import Ball, BallInstance, Player, Special


class CollectorCard(models.Model):
    """A collector tier (Bronze, Silver, Gold). Admins configure these in the admin panel."""

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    emoji = models.CharField(max_length=50, blank=True, null=True)
    special = models.ForeignKey(
        Special,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="collector_cards",
        help_text="Special background awarded when the player claims this tier.",
    )
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "collector_card"
        verbose_name = "Collector Card"
        verbose_name_plural = "Collector Cards"
        ordering = ["name"]

    def __str__(self):
        return self.name


class CollectorRequirement(models.Model):
    """Per-ball threshold for a collector tier."""

    card = models.ForeignKey(
        CollectorCard,
        on_delete=models.CASCADE,
        related_name="requirements",
    )
    ball = models.ForeignKey(
        Ball,
        on_delete=models.CASCADE,
        related_name="collector_requirements",
        verbose_name="Collectible",
    )
    count = models.PositiveIntegerField(
        help_text="How many of this collectible the player must own to claim this tier.",
    )

    class Meta:
        db_table = "collector_requirement"
        unique_together = [("card", "ball")]
        ordering = ["ball__rarity"]
        verbose_name = "Collector Requirement"
        verbose_name_plural = "Collector Requirements"

    def __str__(self):
        return f"{self.card.name} — {self.ball} × {self.count:,}"


class PlayerCollectorCard(models.Model):
    """
    A record of a player claiming a collector tier for a specific ball.
    ball_instance holds the actual awarded card in their collection.
    """

    player = models.ForeignKey(
        Player,
        on_delete=models.CASCADE,
        related_name="collector_cards",
    )
    card = models.ForeignKey(
        CollectorCard,
        on_delete=models.CASCADE,
        related_name="holders",
        verbose_name="Tier",
    )
    ball = models.ForeignKey(
        Ball,
        on_delete=models.CASCADE,
        related_name="collector_claims",
        verbose_name="Collectible",
    )
    ball_instance = models.OneToOneField(
        BallInstance,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="collector_claim",
        help_text="The BallInstance awarded to the player on claim.",
    )
    claimed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "collector_playercard"
        unique_together = [("player", "card", "ball")]
        ordering = ["-claimed_at"]
        verbose_name = "Player Collector Card"
        verbose_name_plural = "Player Collector Cards"

    def __str__(self):
        return f"{self.player} — {self.card.name} ({self.ball})"
