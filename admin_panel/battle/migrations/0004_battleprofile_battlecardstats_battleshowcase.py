from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("battle", "0003_matchresult"),
    ]

    operations = [
        migrations.CreateModel(
            name="BattleProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("discord_id", models.BigIntegerField(unique=True)),
                ("wins", models.IntegerField(default=0)),
                ("losses", models.IntegerField(default=0)),
                ("current_streak", models.IntegerField(default=0)),
            ],
            options={
                "verbose_name": "Battle Profile",
                "verbose_name_plural": "Battle Profiles",
                "db_table": "battle_profile",
                "ordering": ["-wins"],
            },
        ),
        migrations.CreateModel(
            name="BattleCardStats",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("discord_id", models.BigIntegerField()),
                ("ball_id", models.BigIntegerField()),
                ("total_pts", models.IntegerField(default=0)),
            ],
            options={
                "verbose_name": "Battle Card Stats",
                "verbose_name_plural": "Battle Card Stats",
                "db_table": "battle_card_stats",
                "ordering": ["-total_pts"],
                "unique_together": {("discord_id", "ball_id")},
            },
        ),
        migrations.CreateModel(
            name="BattleShowcase",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("discord_id", models.BigIntegerField(unique=True)),
                ("ball_id", models.BigIntegerField()),
                ("art_type", models.CharField(default="card", max_length=10)),
            ],
            options={
                "verbose_name": "Battle Showcase",
                "verbose_name_plural": "Battle Showcases",
                "db_table": "battle_showcase",
            },
        ),
    ]
