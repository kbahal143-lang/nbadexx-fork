from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="CardStyle",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(help_text="A label for this style preset (e.g. 'Default', 'Gold Theme')", max_length=64, unique=True)),
                ("is_active", models.BooleanField(default=False, help_text="Only ONE style can be active at a time. Activating this will deactivate all others.")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                # Title
                ("title_color", models.CharField(default="#FFFFFF", max_length=7, verbose_name="Color")),
                ("title_gradient_end", models.CharField(blank=True, default="", max_length=7, verbose_name="Gradient End Color")),
                ("title_gradient_dir", models.CharField(choices=[("horizontal", "Horizontal (left → right)"), ("vertical", "Vertical (top → bottom)"), ("diagonal", "Diagonal (top-left → bottom-right)")], default="horizontal", max_length=12, verbose_name="Gradient Direction")),
                ("title_stroke_width", models.IntegerField(default=2, verbose_name="Stroke Width")),
                ("title_stroke_color", models.CharField(default="#000000", max_length=7, verbose_name="Stroke Color")),
                ("title_glow_radius", models.IntegerField(default=0, verbose_name="Glow Radius")),
                ("title_glow_color", models.CharField(default="#FFFFFF", max_length=7, verbose_name="Glow Color")),
                # Ability name
                ("ability_name_color", models.CharField(default="#E6E6E6", max_length=7, verbose_name="Color")),
                ("ability_name_gradient_end", models.CharField(blank=True, default="", max_length=7, verbose_name="Gradient End Color")),
                ("ability_name_gradient_dir", models.CharField(choices=[("horizontal", "Horizontal (left → right)"), ("vertical", "Vertical (top → bottom)"), ("diagonal", "Diagonal (top-left → bottom-right)")], default="horizontal", max_length=12, verbose_name="Gradient Direction")),
                ("ability_name_stroke_width", models.IntegerField(default=2, verbose_name="Stroke Width")),
                ("ability_name_stroke_color", models.CharField(default="#000000", max_length=7, verbose_name="Stroke Color")),
                ("ability_name_glow_radius", models.IntegerField(default=0, verbose_name="Glow Radius")),
                ("ability_name_glow_color", models.CharField(default="#FFFFFF", max_length=7, verbose_name="Glow Color")),
                # Ability desc
                ("ability_desc_color", models.CharField(default="#FFFFFF", max_length=7, verbose_name="Color")),
                ("ability_desc_gradient_end", models.CharField(blank=True, default="", max_length=7, verbose_name="Gradient End Color")),
                ("ability_desc_gradient_dir", models.CharField(choices=[("horizontal", "Horizontal (left → right)"), ("vertical", "Vertical (top → bottom)"), ("diagonal", "Diagonal (top-left → bottom-right)")], default="horizontal", max_length=12, verbose_name="Gradient Direction")),
                ("ability_desc_stroke_width", models.IntegerField(default=1, verbose_name="Stroke Width")),
                ("ability_desc_stroke_color", models.CharField(default="#000000", max_length=7, verbose_name="Stroke Color")),
                ("ability_desc_glow_radius", models.IntegerField(default=0, verbose_name="Glow Radius")),
                ("ability_desc_glow_color", models.CharField(default="#FFFFFF", max_length=7, verbose_name="Glow Color")),
                # Health
                ("health_color", models.CharField(default="#ED7365", max_length=7, verbose_name="Color")),
                ("health_gradient_end", models.CharField(blank=True, default="", max_length=7, verbose_name="Gradient End Color")),
                ("health_gradient_dir", models.CharField(choices=[("horizontal", "Horizontal (left → right)"), ("vertical", "Vertical (top → bottom)"), ("diagonal", "Diagonal (top-left → bottom-right)")], default="horizontal", max_length=12, verbose_name="Gradient Direction")),
                ("health_stroke_width", models.IntegerField(default=1, verbose_name="Stroke Width")),
                ("health_stroke_color", models.CharField(default="#000000", max_length=7, verbose_name="Stroke Color")),
                ("health_glow_radius", models.IntegerField(default=0, verbose_name="Glow Radius")),
                ("health_glow_color", models.CharField(default="#FF0000", max_length=7, verbose_name="Glow Color")),
                # Attack
                ("attack_color", models.CharField(default="#FCC24C", max_length=7, verbose_name="Color")),
                ("attack_gradient_end", models.CharField(blank=True, default="", max_length=7, verbose_name="Gradient End Color")),
                ("attack_gradient_dir", models.CharField(choices=[("horizontal", "Horizontal (left → right)"), ("vertical", "Vertical (top → bottom)"), ("diagonal", "Diagonal (top-left → bottom-right)")], default="horizontal", max_length=12, verbose_name="Gradient Direction")),
                ("attack_stroke_width", models.IntegerField(default=1, verbose_name="Stroke Width")),
                ("attack_stroke_color", models.CharField(default="#000000", max_length=7, verbose_name="Stroke Color")),
                ("attack_glow_radius", models.IntegerField(default=0, verbose_name="Glow Radius")),
                ("attack_glow_color", models.CharField(default="#FFD700", max_length=7, verbose_name="Glow Color")),
                # Credits
                ("credits_auto_color", models.BooleanField(default=True, help_text="Automatically pick black or white based on background brightness. Disable to set a manual color below.", verbose_name="Auto-detect Credits Color")),
                ("credits_color", models.CharField(default="#FFFFFF", help_text="Only used when Auto-detect is OFF", max_length=7, verbose_name="Color")),
                ("credits_gradient_end", models.CharField(blank=True, default="", max_length=7, verbose_name="Gradient End Color")),
                ("credits_gradient_dir", models.CharField(choices=[("horizontal", "Horizontal (left → right)"), ("vertical", "Vertical (top → bottom)"), ("diagonal", "Diagonal (top-left → bottom-right)")], default="horizontal", max_length=12, verbose_name="Gradient Direction")),
                ("credits_stroke_width", models.IntegerField(default=0, verbose_name="Stroke Width")),
                ("credits_stroke_color", models.CharField(default="#000000", max_length=7, verbose_name="Stroke Color")),
                ("credits_glow_radius", models.IntegerField(default=0, verbose_name="Glow Radius")),
                ("credits_glow_color", models.CharField(default="#FFFFFF", max_length=7, verbose_name="Glow Color")),
            ],
            options={
                "verbose_name": "Card Style",
                "verbose_name_plural": "Card Styles",
                "ordering": ["-is_active", "name"],
            },
        ),
    ]
