from typing import TYPE_CHECKING, Any

from django.contrib import admin
from django.forms import Textarea
from django.utils.safestring import mark_safe

from ..models import Special

if TYPE_CHECKING:
    from django.db.models import Field
    from django.http import HttpRequest


@admin.register(Special)
class SpecialAdmin(admin.ModelAdmin):
    save_on_top = True
    fieldsets = [
        (
            None,
            {
                "fields": ["name", "catch_phrase", "rarity", "emoji", "background", "credits"],
            },
        ),
        (
            "Coin Multipliers",
            {
                "fields": ["catch_multiplier", "quicksell_multiplier"],
                "description": (
                    "Control how much this special is worth. "
                    "<b>Catch multiplier</b> scales the coins awarded when catching a ball with this special "
                    "(1.0 = normal, 2.0 = double). "
                    "<b>Quicksell multiplier</b> scales the sell value "
                    "(1.5 = default +50% bonus, 2.0 = double)."
                ),
            },
        ),
        (
            "Battle Bonuses",
            {
                "fields": ["battle_atk_bonus", "battle_def_bonus"],
                "description": (
                    "Flat stat points added <b>on top of</b> a card's normal ATK/DEF when it is used in battle. "
                    "Default is 0 (no bonus). "
                    "Example: setting ATK bonus to 20 means every card with this special gets +20 ATK in battle. "
                    "This bonus is shown on <b>/nba info</b> so players can see it on their card."
                ),
            },
        ),
        (
            "Time range",
            {
                "fields": ["start_date", "end_date"],
                "description": "An optional time range to make the event limited in time. As soon "
                "as the event is loaded in the bot's cache, it will automatically load and unload "
                "at the specified time.",
            },
        ),
        (
            "Advanced",
            {
                "fields": ["tradeable", "hidden"],
                "classes": ["collapse"],
            },
        ),
    ]

    list_display = ["name", "pk", "emoji_display", "catch_multiplier", "quicksell_multiplier", "battle_atk_bonus", "battle_def_bonus", "start_date", "end_date", "rarity", "hidden"]
    list_editable = ["hidden", "rarity", "catch_multiplier", "quicksell_multiplier", "battle_atk_bonus", "battle_def_bonus"]
    list_filter = ["hidden", "tradeable"]

    search_fields = ["name", "catch_phrase", "pk"]

    @admin.display(description="Emoji")
    def emoji_display(self, obj: Special):
        return (
            mark_safe(
                f'<img src="https://cdn.discordapp.com/emojis/{obj.emoji}.png?size=40" '
                f'title="ID: {obj.emoji}" />'
            )
            if obj.emoji and obj.emoji.isdigit()
            else obj.emoji
        )

    def formfield_for_dbfield(
        self, db_field: "Field[Any, Any]", request: "HttpRequest | None", **kwargs: Any
    ) -> "Field[Any, Any] | None":
        if db_field.name == "catch_phrase":
            kwargs["widget"] = Textarea()
        return super().formfield_for_dbfield(db_field, request, **kwargs)  # type: ignore
