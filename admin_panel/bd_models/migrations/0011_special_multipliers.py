from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bd_models', '0010_ball_packable'),
    ]

    operations = [
        migrations.AddField(
            model_name='special',
            name='catch_multiplier',
            field=models.FloatField(
                default=1.0,
                help_text=(
                    'Multiplier applied to catch coins when someone catches a ball with this special. '
                    '1.0 = normal, 2.0 = double coins on catch.'
                ),
            ),
        ),
        migrations.AddField(
            model_name='special',
            name='quicksell_multiplier',
            field=models.FloatField(
                default=1.5,
                help_text=(
                    'Multiplier applied to the quicksell value for balls with this special. '
                    '1.5 = 50% bonus (the default for all specials), 2.0 = double quicksell value.'
                ),
            ),
        ),
    ]
