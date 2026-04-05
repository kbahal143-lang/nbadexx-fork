from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bd_models', '0011_special_multipliers'),
    ]

    operations = [
        migrations.AddField(
            model_name='special',
            name='battle_atk_bonus',
            field=models.IntegerField(
                default=0,
                help_text='Flat attack points added in battle for every card that has this special. '
                          '0 = no bonus. Example: 20 means +20 ATK added on top of the card\'s normal stats.',
            ),
        ),
        migrations.AddField(
            model_name='special',
            name='battle_def_bonus',
            field=models.IntegerField(
                default=0,
                help_text='Flat defense points added in battle for every card that has this special. '
                          '0 = no bonus. Example: 20 means +20 DEF added on top of the card\'s normal stats.',
            ),
        ),
    ]
