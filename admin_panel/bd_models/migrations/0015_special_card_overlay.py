from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bd_models", "0014_alter_ball_options_alter_ballinstance_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="special",
            name="card_overlay",
            field=models.ImageField(
                blank=True,
                help_text=(
                    "Optional image drawn over this special card's artwork and below its "
                    "generated text and details. This takes precedence over the base card's "
                    "overlay."
                ),
                max_length=200,
                null=True,
                upload_to="",
            ),
        ),
    ]
