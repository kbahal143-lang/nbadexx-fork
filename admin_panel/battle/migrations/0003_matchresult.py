from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('battle', '0002_alter_playerposition_id_alter_team_id'),
    ]

    operations = [
        migrations.CreateModel(
            name='MatchResult',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('challenger_discord_id', models.BigIntegerField()),
                ('challenged_discord_id', models.BigIntegerField()),
                ('winner_discord_id', models.BigIntegerField()),
                ('winner_score', models.IntegerField()),
                ('loser_score', models.IntegerField()),
                ('played_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'Match Result',
                'verbose_name_plural': 'Match Results',
                'ordering': ['-played_at'],
                'db_table': 'battle_matchresult',
            },
        ),
    ]
