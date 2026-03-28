from django.contrib import admin
from django.utils.html import format_html

from .models import PlayerPosition, Team


@admin.register(PlayerPosition)
class PlayerPositionAdmin(admin.ModelAdmin):
    list_display = ("ball_name", "primary", "secondary", "ball_rarity", "ball_enabled")
    list_filter = ("primary", "secondary", "ball__enabled")
    search_fields = ("ball__country",)
    ordering = ("ball__country",)
    autocomplete_fields = ("ball",)

    @admin.display(description="Player Name", ordering="ball__country")
    def ball_name(self, obj):
        return obj.ball.country

    @admin.display(description="Rarity", ordering="ball__rarity")
    def ball_rarity(self, obj):
        return f"{obj.ball.rarity:.2f}"

    @admin.display(description="Enabled", boolean=True, ordering="ball__enabled")
    def ball_enabled(self, obj):
        return obj.ball.enabled


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("player_id", "pg_name", "sg_name", "sf_name", "pf_name", "c_name", "complete")
    search_fields = ("player__discord_id",)
    readonly_fields = ("player",)

    @admin.display(description="Complete", boolean=True)
    def complete(self, obj):
        return obj.is_complete()

    def _slot_name(self, inst):
        return inst.ball.country if inst and hasattr(inst, "ball") else "—"

    @admin.display(description="PG")
    def pg_name(self, obj):
        return obj.pg.ball.country if obj.pg_id else "—"

    @admin.display(description="SG")
    def sg_name(self, obj):
        return obj.sg.ball.country if obj.sg_id else "—"

    @admin.display(description="SF")
    def sf_name(self, obj):
        return obj.sf.ball.country if obj.sf_id else "—"

    @admin.display(description="PF")
    def pf_name(self, obj):
        return obj.pf.ball.country if obj.pf_id else "—"

    @admin.display(description="C")
    def c_name(self, obj):
        return obj.c.ball.country if obj.c_id else "—"
