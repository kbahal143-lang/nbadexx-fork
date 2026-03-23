from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bd_models", "0009_ballinstance_deleted_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="ball",
            name="packable",
            field=models.BooleanField(
                default=True,
                help_text="Whether this ball can be obtained from packs",
            ),
        ),
    ]
