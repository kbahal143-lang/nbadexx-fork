from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("bd_models", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PlayerPosition",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                (
                    "ball",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="basketball_position",
                        to="bd_models.ball",
                    ),
                ),
                (
                    "primary",
                    models.CharField(
                        choices=[
                            ("PG", "Point Guard"),
                            ("SG", "Shooting Guard"),
                            ("SF", "Small Forward"),
                            ("PF", "Power Forward"),
                            ("C", "Center"),
                        ],
                        max_length=2,
                    ),
                ),
                (
                    "secondary",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("PG", "Point Guard"),
                            ("SG", "Shooting Guard"),
                            ("SF", "Small Forward"),
                            ("PF", "Power Forward"),
                            ("C", "Center"),
                        ],
                        max_length=2,
                        null=True,
                    ),
                ),
            ],
            options={
                "verbose_name": "Player Position",
                "verbose_name_plural": "Player Positions",
                "db_table": "battle_playerposition",
                "ordering": ["ball__country"],
            },
        ),
        migrations.CreateModel(
            name="Team",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                (
                    "player",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="battle_team",
                        to="bd_models.player",
                    ),
                ),
                (
                    "pg",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="team_pg_slot",
                        to="bd_models.ballinstance",
                        verbose_name="Point Guard",
                    ),
                ),
                (
                    "sg",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="team_sg_slot",
                        to="bd_models.ballinstance",
                        verbose_name="Shooting Guard",
                    ),
                ),
                (
                    "sf",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="team_sf_slot",
                        to="bd_models.ballinstance",
                        verbose_name="Small Forward",
                    ),
                ),
                (
                    "pf",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="team_pf_slot",
                        to="bd_models.ballinstance",
                        verbose_name="Power Forward",
                    ),
                ),
                (
                    "c",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="team_c_slot",
                        to="bd_models.ballinstance",
                        verbose_name="Center",
                    ),
                ),
            ],
            options={
                "verbose_name": "Team",
                "verbose_name_plural": "Teams",
                "db_table": "battle_team",
            },
        ),
    ]
