from django.db import models

from bd_models.models import Special, Player, Ball



class Pack(models.Model):
    id: int
    name = models.CharField(max_length=64, unique=True, help_text="Pack name")
    description = models.TextField(help_text="Pack description", null=True, default=None)
    emoji = models.CharField(max_length=64, help_text="Emoji for this pack", null=True, default=None)
    price = models.IntegerField(help_text="Price in coins to buy this pack")
    cards_count = models.IntegerField(help_text="Number of cards in this pack", default=1)
    min_rarity = models.FloatField(help_text="Minimum rarity of balls in this pack", default=0.0)
    max_rarity = models.FloatField(help_text="Maximum rarity of balls in this pack", default=100.0)
    special = models.ForeignKey(
        Special, null=True, blank=True, default=None, on_delete=models.SET_NULL,
        help_text="Optional: only give balls from this special event"
    )
    special_only = models.BooleanField(default=False, help_text="Only include special cards in this pack")
    daily_limit = models.IntegerField(help_text="Maximum packs a player can open per day (0 = unlimited)", default=0)
    enabled = models.BooleanField(default=True, help_text="Whether this pack is available for purchase")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        emoji = (self.emoji + " ") if self.emoji else ""
        return f"{emoji}{self.name}"


class PlayerPack(models.Model):
    id: int
    player = models.ForeignKey(
        Player, related_name="playerpacks", on_delete=models.CASCADE
    )
    pack = models.ForeignKey(
        Pack, related_name="playerpacks", on_delete=models.CASCADE
    )
    quantity = models.IntegerField(default=0, help_text="Number of packs owned")

    def __str__(self) -> str:
        return f"{self.player} - {self.pack} x{self.quantity}"

    class Meta:
        unique_together = ("player", "pack")


class PackOpenHistory(models.Model):
    id: int
    player = models.ForeignKey(
        Player, related_name="pack_opens", on_delete=models.CASCADE
    )
    pack = models.ForeignKey(
        Pack, related_name="pack_opens", on_delete=models.CASCADE
    )
    opened_at = models.DateTimeField(auto_now_add=True)
    cards_received = models.IntegerField(help_text="Number of cards received", default=1)

    def __str__(self) -> str:
        return f"{self.player} opened {self.pack}"


class PlayerMoney(models.Model):
    id: int
    player = models.OneToOneField(Player, on_delete=models.CASCADE)
    coins = models.IntegerField(help_text="Player coins", default=0)


class BallValue(models.Model):
    id: int
    ball = models.OneToOneField(Ball, on_delete=models.CASCADE)
    quicksell_value = models.IntegerField(help_text="Coins received when quickselling this ball", default=100)
