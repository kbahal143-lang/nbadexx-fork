from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("bd_models", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Auction",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("min_bid", models.IntegerField(default=100)),
                ("min_increment", models.IntegerField(default=100)),
                ("buyout_price", models.IntegerField(blank=True, null=True)),
                ("current_bid", models.IntegerField(default=0)),
                (
                    "current_bidder_id",
                    models.BigIntegerField(blank=True, null=True),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("active", "Active"),
                            ("ended", "Ended"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="active",
                        max_length=16,
                    ),
                ),
                ("end_time", models.DateTimeField()),
                ("original_end_time", models.DateTimeField()),
                (
                    "message_id",
                    models.BigIntegerField(blank=True, null=True),
                ),
                (
                    "channel_id",
                    models.BigIntegerField(blank=True, null=True),
                ),
                (
                    "image_url",
                    models.CharField(blank=True, max_length=512, null=True),
                ),
                ("created_by_id", models.BigIntegerField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "winner_instance_id",
                    models.BigIntegerField(blank=True, null=True),
                ),
                (
                    "ball",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="auctions",
                        to="bd_models.ball",
                    ),
                ),
                (
                    "special",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="auctions",
                        to="bd_models.special",
                    ),
                ),
            ],
            options={
                "verbose_name": "Auction",
                "verbose_name_plural": "Auctions",
                "db_table": "auction_auction",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="AuctionBid",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("bidder_discord_id", models.BigIntegerField()),
                ("amount", models.IntegerField()),
                ("bid_at", models.DateTimeField(auto_now_add=True)),
                (
                    "auction",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bids",
                        to="auction.auction",
                    ),
                ),
            ],
            options={
                "verbose_name": "Auction Bid",
                "verbose_name_plural": "Auction Bids",
                "db_table": "auction_auctionbid",
                "ordering": ["-bid_at"],
            },
        ),
    ]
