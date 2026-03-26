from django.contrib import admin

from .models import Season


@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = ("name", "ball_count")
    search_fields = ("name",)
    filter_horizontal = ("balls",)

    def ball_count(self, obj: Season) -> int:
        return obj.balls.count()

    ball_count.short_description = "Collectibles"
