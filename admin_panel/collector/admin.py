from django.contrib import admin

from .models import CollectorCard, CollectorRequirement, PlayerCollectorCard


class CollectorRequirementInline(admin.TabularInline):
    model = CollectorRequirement
    extra = 1
    autocomplete_fields = ["ball"]
    fields = ["ball", "count"]


@admin.register(CollectorCard)
class CollectorCardAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "special",
        "emoji_display",
        "enabled",
        "requirement_count",
        "total_claims",
        "created_at",
    ]
    list_editable = ["enabled"]
    list_filter = ["enabled", "special", "created_at"]
    search_fields = ["name", "description"]
    ordering = ["name"]
    autocomplete_fields = ["special"]
    inlines = [CollectorRequirementInline]
    fields = ["name", "description", "emoji", "special", "enabled"]

    @admin.display(description="Emoji")
    def emoji_display(self, obj):
        return obj.emoji or "—"

    @admin.display(description="Balls configured")
    def requirement_count(self, obj):
        return obj.requirements.count()

    @admin.display(description="Total claims")
    def total_claims(self, obj):
        return obj.holders.count()


@admin.register(PlayerCollectorCard)
class PlayerCollectorCardAdmin(admin.ModelAdmin):
    list_display = ["player", "card", "ball", "claimed_at"]
    list_filter = ["card", "ball", "claimed_at"]
    search_fields = ["player__discord_id", "card__name", "ball__country"]
    ordering = ["-claimed_at"]
    autocomplete_fields = ["player", "card", "ball"]
    readonly_fields = ["claimed_at", "ball_instance"]

    def has_change_permission(self, request, obj=None):
        return False
