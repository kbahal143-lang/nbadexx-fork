from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bd_models", "0012_special_battle_bonuses"),
    ]

    operations = [
        migrations.AddField(
            model_name="ball",
            name="card_overlay",
            field=models.ImageField(
                blank=True,
                null=True,
                max_length=200,
                upload_to="",
                help_text="Optional image overlaid on top of the finished card (drawn last).",
            ),
        ),
        migrations.AddField(
            model_name="ball",
            name="card_full_override",
            field=models.ImageField(
                blank=True,
                null=True,
                max_length=200,
                upload_to="",
                help_text="Optional full-card image that replaces the entire card output, "
                "ignoring background, artwork, text, stats and every other element.",
            ),
        ),
    ]
