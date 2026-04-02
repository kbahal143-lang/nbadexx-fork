from tortoise import models, fields


class Auction(models.Model):
    id: int
    ball = fields.ForeignKeyField(
        "models.Ball", on_delete=fields.CASCADE, related_name="auctions"
    )
    special = fields.ForeignKeyField(
        "models.Special", on_delete=fields.SET_NULL, null=True, related_name="auctions"
    )
    min_bid = fields.IntField(default=100)
    min_increment = fields.IntField(default=100)
    buyout_price = fields.IntField(null=True, default=None)
    current_bid = fields.IntField(default=0)
    current_bidder_id = fields.BigIntField(null=True, default=None)
    status = fields.CharField(max_length=16, default="active")
    end_time = fields.DatetimeField()
    original_end_time = fields.DatetimeField()
    message_id = fields.BigIntField(null=True, default=None)
    channel_id = fields.BigIntField(null=True, default=None)
    image_url = fields.CharField(max_length=512, null=True, default=None)
    created_by_id = fields.BigIntField()
    created_at = fields.DatetimeField(auto_now_add=True)
    winner_instance_id = fields.BigIntField(null=True, default=None)

    class Meta:
        table = "auction_auction"


class AuctionBid(models.Model):
    id: int
    auction = fields.ForeignKeyField(
        "models.Auction", related_name="bids", on_delete=fields.CASCADE
    )
    bidder_discord_id = fields.BigIntField()
    amount = fields.IntField()
    bid_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "auction_auctionbid"
