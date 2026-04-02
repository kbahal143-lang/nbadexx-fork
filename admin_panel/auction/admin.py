from django.contrib import admin

from .models import Auction, AuctionBid


class AuctionBidInline(admin.TabularInline):
    model = AuctionBid
    readonly_fields = ("bidder_discord_id", "amount", "bid_at")
    extra = 0
    can_delete = False
    ordering = ("-bid_at",)


@admin.register(Auction)
class AuctionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "ball_name",
        "status",
        "current_bid",
        "current_bidder_id",
        "end_time",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("ball__country", "current_bidder_id", "created_by_id")
    readonly_fields = (
        "created_at",
        "message_id",
        "channel_id",
        "image_url",
        "winner_instance_id",
    )
    inlines = [AuctionBidInline]
    ordering = ("-created_at",)

    @admin.display(description="NBA Card", ordering="ball__country")
    def ball_name(self, obj):
        return obj.ball.country


@admin.register(AuctionBid)
class AuctionBidAdmin(admin.ModelAdmin):
    list_display = ("id", "auction_id", "bidder_discord_id", "amount", "bid_at")
    list_filter = ("auction",)
    search_fields = ("bidder_discord_id",)
    readonly_fields = ("bid_at",)
    ordering = ("-bid_at",)
