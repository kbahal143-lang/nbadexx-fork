from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("bd_models", "0015_special_card_overlay"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="ball",
            options={
                "managed": True,
                "verbose_name": "ball",
                "verbose_name_plural": "balls",
            },
        ),
        migrations.AlterModelOptions(
            name="ballinstance",
            options={"managed": True, "verbose_name": "ball instance"},
        ),
    ]
