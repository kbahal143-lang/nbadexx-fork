from django.db import models


GRADIENT_DIR_CHOICES = [
    ("horizontal", "Horizontal (left → right)"),
    ("vertical", "Vertical (top → bottom)"),
    ("diagonal", "Diagonal (top-left → bottom-right)"),
]


class CardStyle(models.Model):
    name = models.CharField(
        max_length=64, unique=True,
        help_text="A label for this style preset (e.g. 'Gold Theme', 'LeBron Special')"
    )
    balls = models.ManyToManyField(
        "bd_models.Ball",
        blank=True,
        verbose_name="Collectibles",
        related_name="card_styles",
        help_text="Which player cards use this style. A card not listed here keeps its default look.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ── CARD NAME (top title) ──────────────────────────────────────────────
    title_color = models.CharField(max_length=7, default="#FFFFFF", verbose_name="Color")
    title_gradient_end = models.CharField(max_length=7, blank=True, default="", verbose_name="Gradient End Color", help_text="Leave empty for solid. Set a color to enable gradient.")
    title_gradient_dir = models.CharField(max_length=12, choices=GRADIENT_DIR_CHOICES, default="horizontal", verbose_name="Gradient Direction")
    title_stroke_width = models.IntegerField(default=2, verbose_name="Stroke Width", help_text="Outline thickness in pixels (0 = none)")
    title_stroke_color = models.CharField(max_length=7, default="#000000", verbose_name="Stroke Color")
    title_glow_radius = models.IntegerField(default=0, verbose_name="Glow Radius", help_text="Glow blur radius in pixels (0 = none)")
    title_glow_color = models.CharField(max_length=7, default="#FFFFFF", verbose_name="Glow Color")

    # ── ABILITY NAME ──────────────────────────────────────────────────────
    ability_name_color = models.CharField(max_length=7, default="#E6E6E6", verbose_name="Color")
    ability_name_gradient_end = models.CharField(max_length=7, blank=True, default="", verbose_name="Gradient End Color")
    ability_name_gradient_dir = models.CharField(max_length=12, choices=GRADIENT_DIR_CHOICES, default="horizontal", verbose_name="Gradient Direction")
    ability_name_stroke_width = models.IntegerField(default=2, verbose_name="Stroke Width")
    ability_name_stroke_color = models.CharField(max_length=7, default="#000000", verbose_name="Stroke Color")
    ability_name_glow_radius = models.IntegerField(default=0, verbose_name="Glow Radius")
    ability_name_glow_color = models.CharField(max_length=7, default="#FFFFFF", verbose_name="Glow Color")

    # ── ABILITY DESCRIPTION ───────────────────────────────────────────────
    ability_desc_color = models.CharField(max_length=7, default="#FFFFFF", verbose_name="Color")
    ability_desc_gradient_end = models.CharField(max_length=7, blank=True, default="", verbose_name="Gradient End Color")
    ability_desc_gradient_dir = models.CharField(max_length=12, choices=GRADIENT_DIR_CHOICES, default="horizontal", verbose_name="Gradient Direction")
    ability_desc_stroke_width = models.IntegerField(default=1, verbose_name="Stroke Width")
    ability_desc_stroke_color = models.CharField(max_length=7, default="#000000", verbose_name="Stroke Color")
    ability_desc_glow_radius = models.IntegerField(default=0, verbose_name="Glow Radius")
    ability_desc_glow_color = models.CharField(max_length=7, default="#FFFFFF", verbose_name="Glow Color")

    # ── HEALTH STAT ───────────────────────────────────────────────────────
    health_color = models.CharField(max_length=7, default="#ED7365", verbose_name="Color")
    health_gradient_end = models.CharField(max_length=7, blank=True, default="", verbose_name="Gradient End Color")
    health_gradient_dir = models.CharField(max_length=12, choices=GRADIENT_DIR_CHOICES, default="horizontal", verbose_name="Gradient Direction")
    health_stroke_width = models.IntegerField(default=1, verbose_name="Stroke Width")
    health_stroke_color = models.CharField(max_length=7, default="#000000", verbose_name="Stroke Color")
    health_glow_radius = models.IntegerField(default=0, verbose_name="Glow Radius")
    health_glow_color = models.CharField(max_length=7, default="#FF0000", verbose_name="Glow Color")

    # ── ATTACK STAT ───────────────────────────────────────────────────────
    attack_color = models.CharField(max_length=7, default="#FCC24C", verbose_name="Color")
    attack_gradient_end = models.CharField(max_length=7, blank=True, default="", verbose_name="Gradient End Color")
    attack_gradient_dir = models.CharField(max_length=12, choices=GRADIENT_DIR_CHOICES, default="horizontal", verbose_name="Gradient Direction")
    attack_stroke_width = models.IntegerField(default=1, verbose_name="Stroke Width")
    attack_stroke_color = models.CharField(max_length=7, default="#000000", verbose_name="Stroke Color")
    attack_glow_radius = models.IntegerField(default=0, verbose_name="Glow Radius")
    attack_glow_color = models.CharField(max_length=7, default="#FFD700", verbose_name="Glow Color")

    # ── CREDITS ───────────────────────────────────────────────────────────
    credits_auto_color = models.BooleanField(default=True, verbose_name="Auto-detect Credits Color", help_text="Auto-picks black or white based on background. Uncheck to set manually.")
    credits_color = models.CharField(max_length=7, default="#FFFFFF", verbose_name="Color", help_text="Only used when Auto-detect is OFF")
    credits_gradient_end = models.CharField(max_length=7, blank=True, default="", verbose_name="Gradient End Color")
    credits_gradient_dir = models.CharField(max_length=12, choices=GRADIENT_DIR_CHOICES, default="horizontal", verbose_name="Gradient Direction")
    credits_stroke_width = models.IntegerField(default=0, verbose_name="Stroke Width")
    credits_stroke_color = models.CharField(max_length=7, default="#000000", verbose_name="Stroke Color")
    credits_glow_radius = models.IntegerField(default=0, verbose_name="Glow Radius")
    credits_glow_color = models.CharField(max_length=7, default="#FFFFFF", verbose_name="Glow Color")

    class Meta:
        verbose_name = "Card Style"
        verbose_name_plural = "Card Styles"
        ordering = ["name"]

    def __str__(self):
        count = self.balls.count() if self.pk else 0
        return f"{self.name} ({count} card{'s' if count != 1 else ''})"
