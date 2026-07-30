from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("battle", "0004_battleprofile_battlecardstats_battleshowcase"),
    ]

    operations = [
        migrations.RenameField(
            model_name="battleshowcase",
            old_name="ball_id",
            new_name="instance_id",
        ),
    ]
