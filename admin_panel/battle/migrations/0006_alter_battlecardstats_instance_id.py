from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Replace ball_id with instance_id on BattleCardStats.
    Stats now travel with the specific card instance rather than the ball type.
    Existing rows are dropped because they referenced ball_id which no longer exists.
    """

    dependencies = [
        ("battle", "0005_rename_ball_id_battleshowcase_instance_id"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "DELETE FROM battle_card_stats;\n"
                        "ALTER TABLE battle_card_stats DROP COLUMN ball_id;\n"
                        "ALTER TABLE battle_card_stats ADD COLUMN instance_id bigint NOT NULL DEFAULT 0;\n"
                        "ALTER TABLE battle_card_stats DROP CONSTRAINT IF EXISTS "
                        "battle_card_stats_discord_id_ball_id_key;\n"
                        "ALTER TABLE battle_card_stats ADD CONSTRAINT "
                        "battle_card_stats_discord_id_instance_id_key "
                        "UNIQUE (discord_id, instance_id);\n"
                        "ALTER TABLE battle_card_stats ALTER COLUMN instance_id DROP DEFAULT;"
                    ),
                    reverse_sql=(
                        "DELETE FROM battle_card_stats;\n"
                        "ALTER TABLE battle_card_stats DROP COLUMN instance_id;\n"
                        "ALTER TABLE battle_card_stats ADD COLUMN ball_id bigint NOT NULL DEFAULT 0;\n"
                        "ALTER TABLE battle_card_stats DROP CONSTRAINT IF EXISTS "
                        "battle_card_stats_discord_id_instance_id_key;\n"
                        "ALTER TABLE battle_card_stats ADD CONSTRAINT "
                        "battle_card_stats_discord_id_ball_id_key "
                        "UNIQUE (discord_id, ball_id);\n"
                        "ALTER TABLE battle_card_stats ALTER COLUMN ball_id DROP DEFAULT;"
                    ),
                ),
            ],
            state_operations=[
                migrations.RemoveField(
                    model_name="battlecardstats",
                    name="ball_id",
                ),
                migrations.AddField(
                    model_name="battlecardstats",
                    name="instance_id",
                    field=models.BigIntegerField(),
                ),
                migrations.AlterUniqueTogether(
                    name="battlecardstats",
                    unique_together={("discord_id", "instance_id")},
                ),
            ],
        ),
    ]
