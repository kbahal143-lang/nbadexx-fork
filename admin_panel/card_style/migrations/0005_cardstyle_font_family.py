from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("card_style", "0004_cardstyle_special"),
    ]

    operations = [
        migrations.AddField(
            model_name="cardstyle",
            name="font_family",
            field=models.CharField(
                choices=[
                    ("default", "Original NBADex fonts (default)"),
                    ("roboto_condensed", "Roboto Condensed — screenshot-style condensed"),
                    ("bebas_neue", "Bebas Neue — bold sports headline"),
                    ("anton", "Anton — strong poster headline"),
                    ("oswald", "Oswald — clean condensed"),
                    ("barlow_condensed", "Barlow Condensed — modern athletic"),
                    ("rajdhani", "Rajdhani — sharp futuristic"),
                    ("teko", "Teko — tall display"),
                    ("orbitron", "Orbitron — sci-fi geometric"),
                    ("audiowide", "Audiowide — wide futuristic"),
                    ("black_ops_one", "Black Ops One — impact display"),
                    ("exo_2", "Exo 2 — polished tech"),
                    ("space_grotesk", "Space Grotesk — premium geometric"),
                    ("cinzel", "Cinzel — classic monumental"),
                ],
                default="default",
                help_text=(
                    "Changes every text element on assigned cards. "
                    "Original NBADex fonts remain the default."
                ),
                max_length=32,
                verbose_name="Card Font",
            ),
        ),
    ]