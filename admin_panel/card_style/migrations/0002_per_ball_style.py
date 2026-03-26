from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bd_models", "0001_initial"),
        ("card_style", "0001_initial"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="cardstyle",
            name="is_active",
        ),
        migrations.AlterModelOptions(
            name="cardstyle",
            options={
                "verbose_name": "Card Style",
                "verbose_name_plural": "Card Styles",
                "ordering": ["name"],
            },
        ),
        migrations.AddField(
            model_name="cardstyle",
            name="balls",
            field=models.ManyToManyField(
                blank=True,
                help_text="Which player cards use this style. A card not listed here keeps its default look.",
                related_name="card_styles",
                to="bd_models.ball",
                verbose_name="Collectibles",
            ),
        ),
    ]
