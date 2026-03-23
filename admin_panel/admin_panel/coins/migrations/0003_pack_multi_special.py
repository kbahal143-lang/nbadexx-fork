from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bd_models', '0010_ball_packable'),
        ('coins', '0002_alter_pack_special'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='pack',
            name='special',
        ),
        migrations.AlterField(
            model_name='pack',
            name='special_only',
            field=models.BooleanField(
                default=False,
                help_text="Filter ball pool to only balls that have an existing instance with one of the allowed specials",
            ),
        ),
        migrations.AddField(
            model_name='pack',
            name='special_chance',
            field=models.BooleanField(
                default=True,
                help_text=(
                    "On: specials appear by probability from the allowed pool. "
                    "Off: every card is guaranteed a special "
                    "(1 allowed = that one always; multiple = equal weight random pick)"
                ),
            ),
        ),
        migrations.AddField(
            model_name='pack',
            name='allowed_specials',
            field=models.ManyToManyField(
                blank=True,
                db_table='coins_pack_allowed_specials',
                help_text="Specials that can appear in this pack (empty = all active specials when Special Chance is on)",
                to='bd_models.special',
            ),
        ),
    ]
