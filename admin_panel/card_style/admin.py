from django import forms
from django.contrib import admin
from django.utils.html import format_html

from .models import CardStyle


class ColorInput(forms.TextInput):
    input_type = "color"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.attrs.setdefault("style", "width:60px;height:36px;padding:2px;cursor:pointer;")


class CardStyleForm(forms.ModelForm):
    title_color = forms.CharField(widget=ColorInput(), label="Color", initial="#FFFFFF")
    title_gradient_end = forms.CharField(widget=ColorInput(), label="Gradient End Color", required=False, initial="")
    title_stroke_color = forms.CharField(widget=ColorInput(), label="Stroke Color", initial="#000000")
    title_glow_color = forms.CharField(widget=ColorInput(), label="Glow Color", initial="#FFFFFF")

    ability_name_color = forms.CharField(widget=ColorInput(), label="Color", initial="#E6E6E6")
    ability_name_gradient_end = forms.CharField(widget=ColorInput(), label="Gradient End Color", required=False, initial="")
    ability_name_stroke_color = forms.CharField(widget=ColorInput(), label="Stroke Color", initial="#000000")
    ability_name_glow_color = forms.CharField(widget=ColorInput(), label="Glow Color", initial="#FFFFFF")

    ability_desc_color = forms.CharField(widget=ColorInput(), label="Color", initial="#FFFFFF")
    ability_desc_gradient_end = forms.CharField(widget=ColorInput(), label="Gradient End Color", required=False, initial="")
    ability_desc_stroke_color = forms.CharField(widget=ColorInput(), label="Stroke Color", initial="#000000")
    ability_desc_glow_color = forms.CharField(widget=ColorInput(), label="Glow Color", initial="#FFFFFF")

    health_color = forms.CharField(widget=ColorInput(), label="Color", initial="#ED7365")
    health_gradient_end = forms.CharField(widget=ColorInput(), label="Gradient End Color", required=False, initial="")
    health_stroke_color = forms.CharField(widget=ColorInput(), label="Stroke Color", initial="#000000")
    health_glow_color = forms.CharField(widget=ColorInput(), label="Glow Color", initial="#FF0000")

    attack_color = forms.CharField(widget=ColorInput(), label="Color", initial="#FCC24C")
    attack_gradient_end = forms.CharField(widget=ColorInput(), label="Gradient End Color", required=False, initial="")
    attack_stroke_color = forms.CharField(widget=ColorInput(), label="Stroke Color", initial="#000000")
    attack_glow_color = forms.CharField(widget=ColorInput(), label="Glow Color", initial="#FFD700")

    credits_color = forms.CharField(widget=ColorInput(), label="Color", initial="#FFFFFF")
    credits_gradient_end = forms.CharField(widget=ColorInput(), label="Gradient End Color", required=False, initial="")
    credits_stroke_color = forms.CharField(widget=ColorInput(), label="Stroke Color", initial="#000000")
    credits_glow_color = forms.CharField(widget=ColorInput(), label="Glow Color", initial="#FFFFFF")

    class Meta:
        model = CardStyle
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        gradient_fields = [
            "title_gradient_end", "ability_name_gradient_end",
            "ability_desc_gradient_end", "health_gradient_end",
            "attack_gradient_end", "credits_gradient_end",
        ]
        for f in gradient_fields:
            cleaned[f] = cleaned.get(f, "").strip()
        return cleaned


@admin.register(CardStyle)
class CardStyleAdmin(admin.ModelAdmin):
    form = CardStyleForm
    list_display = ["name", "ball_count", "ball_names", "updated_at"]
    list_display_links = ["name"]
    ordering = ["name"]
    filter_horizontal = ["balls"]
    search_fields = ["name", "balls__country"]
    save_on_top = True

    fieldsets = (
        ("Preset Info", {
            "fields": ("name", "balls"),
            "description": (
                "<div style='background:#d4edda;padding:10px;border-radius:6px;margin-bottom:8px;'>"
                "<strong>How it works:</strong> Choose which player cards use this style. "
                "Any card not assigned to a style will keep its original default appearance. "
                "One card can only have one style — if a card appears in multiple presets, "
                "the most recently updated preset wins."
                "</div>"
            ),
        }),
        ("🏷️ Card Name (top title)", {
            "fields": (
                "title_color",
                ("title_gradient_end", "title_gradient_dir"),
                ("title_stroke_width", "title_stroke_color"),
                ("title_glow_radius", "title_glow_color"),
            ),
            "description": "<em>The large player name shown at the top of the card.</em>",
        }),
        ("⚡ Ability Name", {
            "fields": (
                "ability_name_color",
                ("ability_name_gradient_end", "ability_name_gradient_dir"),
                ("ability_name_stroke_width", "ability_name_stroke_color"),
                ("ability_name_glow_radius", "ability_name_glow_color"),
            ),
            "description": "<em>'ABILITY: ...' label in the lower section.</em>",
        }),
        ("📝 Ability Description", {
            "fields": (
                "ability_desc_color",
                ("ability_desc_gradient_end", "ability_desc_gradient_dir"),
                ("ability_desc_stroke_width", "ability_desc_stroke_color"),
                ("ability_desc_glow_radius", "ability_desc_glow_color"),
            ),
            "description": "<em>The ability text below the ability name.</em>",
        }),
        ("❤️ Health Stat", {
            "fields": (
                "health_color",
                ("health_gradient_end", "health_gradient_dir"),
                ("health_stroke_width", "health_stroke_color"),
                ("health_glow_radius", "health_glow_color"),
            ),
            "description": "<em>The health number on the bottom-left of the card.</em>",
        }),
        ("⚔️ Attack Stat", {
            "fields": (
                "attack_color",
                ("attack_gradient_end", "attack_gradient_dir"),
                ("attack_stroke_width", "attack_stroke_color"),
                ("attack_glow_radius", "attack_glow_color"),
            ),
            "description": "<em>The attack number on the bottom-right of the card.</em>",
        }),
        ("🖊️ Credits (Created by / Artwork author)", {
            "fields": (
                "credits_auto_color",
                "credits_color",
                ("credits_gradient_end", "credits_gradient_dir"),
                ("credits_stroke_width", "credits_stroke_color"),
                ("credits_glow_radius", "credits_glow_color"),
            ),
            "description": "<em>The small text at the very bottom of the card.</em>",
        }),
    )

    def ball_count(self, obj):
        count = obj.balls.count()
        if count == 0:
            return format_html('<span style="color:#999">None assigned</span>')
        return format_html(
            '<span style="background:#007bff;color:white;padding:2px 8px;'
            'border-radius:10px;font-size:12px;">{} card{}</span>',
            count,
            "s" if count != 1 else "",
        )
    ball_count.short_description = "Cards"

    def ball_names(self, obj):
        names = list(obj.balls.values_list("country", flat=True)[:6])
        if not names:
            return "—"
        text = ", ".join(names)
        total = obj.balls.count()
        if total > 6:
            text += f" … +{total - 6} more"
        return text
    ball_names.short_description = "Assigned to"
