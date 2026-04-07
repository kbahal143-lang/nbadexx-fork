import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("bd_models", "0012_special_battle_bonuses"),
    ]

    operations = [
        migrations.CreateModel(
            name="CollectorCard",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False
                    ),
                ),
                ("name", models.CharField(max_length=100)),
                ("description", models.TextField(blank=True)),
                ("emoji", models.CharField(blank=True, max_length=50, null=True)),
                ("enabled", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "special",
                    models.ForeignKey(
                        blank=True,
                        help_text="Special background awarded when the player claims this tier.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="collector_cards",
                        to="bd_models.special",
                    ),
                ),
            ],
            options={
                "verbose_name": "Collector Card",
                "verbose_name_plural": "Collector Cards",
                "db_table": "collector_card",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="CollectorRequirement",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False
                    ),
                ),
                (
                    "count",
                    models.PositiveIntegerField(
                        help_text="How many of this collectible the player must own to claim this tier."
                    ),
                ),
                (
                    "ball",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="collector_requirements",
                        to="bd_models.ball",
                        verbose_name="Collectible",
                    ),
                ),
                (
                    "card",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="requirements",
                        to="collector.collectorcard",
                    ),
                ),
            ],
            options={
                "verbose_name": "Collector Requirement",
                "verbose_name_plural": "Collector Requirements",
                "db_table": "collector_requirement",
                "ordering": ["ball__rarity"],
            },
        ),
        migrations.CreateModel(
            name="PlayerCollectorCard",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False
                    ),
                ),
                ("claimed_at", models.DateTimeField(auto_now_add=True)),
                (
                    "ball",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="collector_claims",
                        to="bd_models.ball",
                        verbose_name="Collectible",
                    ),
                ),
                (
                    "ball_instance",
                    models.OneToOneField(
                        blank=True,
                        help_text="The BallInstance awarded to the player on claim.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="collector_claim",
                        to="bd_models.ballinstance",
                    ),
                ),
                (
                    "card",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="holders",
                        to="collector.collectorcard",
                        verbose_name="Tier",
                    ),
                ),
                (
                    "player",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="collector_cards",
                        to="bd_models.player",
                    ),
                ),
            ],
            options={
                "verbose_name": "Player Collector Card",
                "verbose_name_plural": "Player Collector Cards",
                "db_table": "collector_playercard",
                "ordering": ["-claimed_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="collectorrequirement",
            constraint=models.UniqueConstraint(
                fields=["card", "ball"], name="unique_collector_requirement"
            ),
        ),
        migrations.AddConstraint(
            model_name="playercollectorcard",
            constraint=models.UniqueConstraint(
                fields=["player", "card", "ball"], name="unique_player_collector_card"
            ),
        ),
    ]
