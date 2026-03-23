from django.contrib import admin

from .models import Pack, PackOpenHistory, PlayerPack, BallValue


@admin.register(Pack)
class PackAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "emoji_display",
        "price",
        "cards_count",
        "rarity_range",
        "special_chance",
        "special_only",
        "daily_limit",
        "enabled",
    ]
    list_editable = ["price", "daily_limit", "enabled", "special_chance", "special_only"]
    list_filter = ["enabled", "special_chance", "special_only", "created_at"]
    search_fields = ["name", "description"]
    ordering = ["price"]
    filter_horizontal = ["allowed_specials"]

    fieldsets = [
        (
            None,
            {
                "fields": [
                    "name",
                    "description",
                    "emoji",
                    "price",
                    "cards_count",
                ],
            },
        ),
        (
            "Rarity Settings",
            {
                "description": "Configure the rarity range for cards in this pack",
                "fields": [
                    "min_rarity",
                    "max_rarity",
                ],
            },
        ),
        (
            "Limits",
            {
                "description": "Configure purchase limits",
                "fields": [
                    "daily_limit",
                ],
            },
        ),
        (
            "Special Settings",
            {
                "description": (
                    "Allowed specials empty + Special chance ON → all active specials by probability. "
                    "Allowed specials set + Special chance ON → only those specials, by rarity weight. "
                    "1 allowed + Special chance OFF → every card gets that special (guaranteed). "
                    "Multiple allowed + Special chance OFF → equal weight random pick per card. "
                    "Special only ON + Allowed specials set → ball pool filtered to balls with those specials."
                ),
                "fields": [
                    "allowed_specials",
                    "special_chance",
                    "special_only",
                ],
            },
        ),
        (
            "Status",
            {
                "fields": [
                    "enabled",
                ],
            },
        ),
    ]

    @admin.display(description="Emoji")
    def emoji_display(self, obj: Pack) -> str:
        return obj.emoji or "-"

    @admin.display(description="Rarity")
    def rarity_range(self, obj: Pack) -> str:
        return f"{obj.min_rarity} - {obj.max_rarity}"


@admin.register(PlayerPack)
class PlayerPackAdmin(admin.ModelAdmin):
    list_display = ["player", "pack", "quantity"]
    list_filter = ["pack"]
    search_fields = ["player__discord_id"]
    autocomplete_fields = ["player", "pack"]


@admin.register(PackOpenHistory)
class PackOpenHistoryAdmin(admin.ModelAdmin):
    list_display = ["player", "pack", "opened_at", "cards_received"]
    list_filter = ["pack", "opened_at"]
    search_fields = ["player__discord_id"]
    ordering = ["-opened_at"]
    readonly_fields = ["player", "pack", "opened_at", "cards_received"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(BallValue)
class BallValueAdmin(admin.ModelAdmin):
    autocomplete_fields = ("ball",)
    list_display = ("ball_name", "quicksell_value")
    list_editable = ("quicksell_value",)
    search_fields = ("ball__country",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("ball")

    @admin.display(description="Ball", ordering="ball__country")
    def ball_name(self, obj):
        return obj.ball.country if obj.ball else "-"
