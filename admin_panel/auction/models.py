from django.db import models

from bd_models.models import Ball, BallInstance


class Auction(models.Model):

    STATUS_CHOICES = [
        ("active", "Active"),
        ("ended", "Ended"),
        ("cancelled", "Cancelled"),
    ]

    ball = models.ForeignKey(
        Ball,
        on_delete=models.CASCADE,
        related_name="auctions",
    )
    special = models.ForeignKey(
        "bd_models.Special",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="auctions",
    )
    min_bid = models.IntegerField(default=100)
    min_increment = models.IntegerField(default=100)
    buyout_price = models.IntegerField(null=True, blank=True)
    current_bid = models.IntegerField(default=0)
    current_bidder_id = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="active")
    end_time = models.DateTimeField()
    original_end_time = models.DateTimeField()
    message_id = models.BigIntegerField(null=True, blank=True)
    channel_id = models.BigIntegerField(null=True, blank=True)
    image_url = models.CharField(max_length=512, null=True, blank=True)
    created_by_id = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    winner_instance_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "auction_auction"
        verbose_name = "Auction"
        verbose_name_plural = "Auctions"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Auction #{self.pk} — {self.ball.country} ({self.status})"


class AuctionBid(models.Model):

    auction = models.ForeignKey(
        Auction,
        on_delete=models.CASCADE,
        related_name="bids",
    )
    bidder_discord_id = models.BigIntegerField()
    amount = models.IntegerField()
    bid_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "auction_auctionbid"
        verbose_name = "Auction Bid"
        verbose_name_plural = "Auction Bids"
        ordering = ["-bid_at"]

    def __str__(self):
        return f"Bid #{self.pk} — {self.amount:,} coins by {self.bidder_discord_id}"
