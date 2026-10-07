from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bd_models", "0013_ball_card_overlay_and_full_override"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="ball",
            options={
                "managed": True,
                "verbose_name": "countryball",
                "verbose_name_plural": "countryballs",
            },
        ),
        migrations.AlterModelOptions(
            name="ballinstance",
            options={"managed": True, "verbose_name": "countryball instance"},
        ),
        migrations.AlterField(
            model_name="ball",
            name="card_overlay",
            field=models.ImageField(
                blank=True,
                help_text=(
                    "Optional image drawn over the collection artwork and below the card name, "
                    "economy icon, stats, ability and credits."
                ),
                max_length=200,
                null=True,
                upload_to="",
            ),
        ),
    ]
