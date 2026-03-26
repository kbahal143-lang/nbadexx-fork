from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("bd_models", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Season",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(help_text="The name of this season (e.g. 'Season 1', 'Playoffs 2025')", max_length=64, unique=True)),
                (
                    "balls",
                    models.ManyToManyField(
                        blank=True,
                        help_text="Which collectibles belong to this season.",
                        related_name="seasons",
                        to="bd_models.ball",
                        verbose_name="Collectibles",
                    ),
                ),
            ],
            options={
                "verbose_name": "Season",
                "verbose_name_plural": "Seasons",
                "ordering": ["name"],
            },
        ),
    ]
