from django.db import models


class Season(models.Model):
    name = models.CharField(
        max_length=64,
        unique=True,
        help_text="The name of this season (e.g. 'Season 1', 'Playoffs 2025')",
    )
    balls = models.ManyToManyField(
        "bd_models.Ball",
        blank=True,
        verbose_name="Collectibles",
        related_name="seasons",
        help_text="Which collectibles belong to this season.",
    )

    class Meta:
        verbose_name = "Season"
        verbose_name_plural = "Seasons"
        ordering = ["name"]

    def __str__(self) -> str:
        count = self.balls.count() if self.pk else 0
        return f"{self.name} ({count} collectible{'s' if count != 1 else ''})"
