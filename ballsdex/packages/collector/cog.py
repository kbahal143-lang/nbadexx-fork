from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Iterable

import discord
from discord import app_commands
from discord.ext import commands, tasks
from tortoise.exceptions import DoesNotExist, IntegrityError

from ballsdex.core.models import Ball, BallInstance, Player, balls
from ballsdex.core.utils.transformers import TTLModelTransformer
from ballsdex.settings import settings

from .models import CollectorCard, CollectorRequirement, PlayerCollectorCard

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.collector")
Interaction = discord.Interaction["BallsDexBot"]

ITEMS_PER_PAGE = 5


# ── Helpers ───────────────────────────────────────────────────────────────────

def ball_emoji(ball: Ball, bot: "BallsDexBot | None" = None) -> str:
    """Return the Discord emoji string for a collectible."""
    if bot is not None:
        emoji = bot.get_emoji(ball.emoji_id)
        if emoji is not None:
            return str(emoji)
    name = ball.country.lower().replace(" ", "_").replace("-", "_").replace("'", "")[:32]
    return f"<:{name}:{ball.emoji_id}>"


async def get_or_create_player(discord_id: int) -> Player:
    player, _ = await Player.get_or_create(discord_id=discord_id)
    return player


async def get_player_count(
    player: Player, ball: Ball, exclude_instance_id: int | None = None
) -> int:
    """
    Count non-deleted BallInstances of a specific ball owned by a player.
    Optionally exclude one instance (the awarded collector card itself)
    so it does not count toward its own revoke threshold.
    """
    qs = BallInstance.filter(player=player, ball=ball, deleted=False)
    if exclude_instance_id:
        qs = qs.exclude(id=exclude_instance_id)
    return await qs.count()


# ── Transformers ──────────────────────────────────────────────────────────────

class CollectorBallTransformer(TTLModelTransformer[Ball]):
    """Autocomplete: only balls that have at least one collector requirement configured."""

    name = settings.collectible_name
    model = Ball()

    def key(self, model: Ball) -> str:
        return model.country

    async def load_items(self) -> Iterable[Ball]:
        req_ball_ids = set(
            await CollectorRequirement.filter(
                card__enabled=True
            ).values_list("ball_id", flat=True)
        )
        return [b for b in balls.values() if b.pk in req_ball_ids and b.enabled]


class CollectorCardTransformer(TTLModelTransformer[CollectorCard]):
    """
    Autocomplete: enabled collector tiers.
    If the user has already picked a collectible, only show tiers configured for that ball.
    """

    name = "collector tier"
    model = CollectorCard()

    def __init__(self):
        super().__init__()
        self._card_ball_ids: dict[int, set[int]] = {}

    def key(self, card: CollectorCard) -> str:
        return f"{card.emoji + ' ' if card.emoji else ''}{card.name}"

    async def load_items(self) -> Iterable[CollectorCard]:
        cards = await CollectorCard.filter(enabled=True).all()
        self._card_ball_ids = {}
        for row in await CollectorRequirement.filter(card__enabled=True).values(
            "card_id", "ball_id"
        ):
            self._card_ball_ids.setdefault(row["card_id"], set()).add(row["ball_id"])
        return cards

    async def get_options(
        self, interaction: Interaction, value: str
    ) -> list[app_commands.Choice[str]]:
        await self.maybe_refresh()

        ball_id_str = getattr(interaction.namespace, "collectible", None)
        try:
            ball_id = int(ball_id_str) if ball_id_str else None
        except (ValueError, TypeError):
            ball_id = None

        i = 0
        choices: list[app_commands.Choice[str]] = []
        for card in self.items.values():
            if ball_id and ball_id not in self._card_ball_ids.get(card.pk, set()):
                continue
            if value.lower() in self.search_map[card]:
                choices.append(app_commands.Choice(name=self.key(card), value=str(card.pk)))
                i += 1
                if i == 25:
                    break
        return choices


CollectorBallTransform = app_commands.Transform[Ball, CollectorBallTransformer]
CollectorCardTransform = app_commands.Transform[CollectorCard, CollectorCardTransformer]


# ── Paginated list view ───────────────────────────────────────────────────────

class CollectorListView(discord.ui.View):
    """Paginated embed — every ball with its per-tier thresholds."""

    def __init__(self, interaction: Interaction, pages: list[discord.Embed]):
        super().__init__(timeout=120)
        self.interaction = interaction
        self.pages = pages
        self.page = 0
        self._refresh_buttons()

    def _refresh_buttons(self):
        self.prev_btn.disabled = self.page == 0
        self.next_btn.disabled = self.page >= len(self.pages) - 1

    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.id != self.interaction.user.id:
            await interaction.response.send_message(
                "This menu isn't yours!", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: Interaction, button: discord.ui.Button):
        self.page -= 1
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.pages[self.page], view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: Interaction, button: discord.ui.Button):
        self.page += 1
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.pages[self.page], view=self)

    @discord.ui.button(label="✖ Close", style=discord.ButtonStyle.danger)
    async def close_btn(self, interaction: Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True  # type: ignore
        await interaction.response.edit_message(view=self)
        self.stop()

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True  # type: ignore
        try:
            await self.interaction.edit_original_response(view=self)
        except discord.HTTPException:
            pass


# ── Main cog ──────────────────────────────────────────────────────────────────

class CollectorCog(commands.GroupCog, name="collector"):
    """Collector card system — collect enough of a specific card to earn a special version!"""

    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot

    async def cog_load(self):
        self._revoke_task.start()

    async def cog_unload(self):
        self._revoke_task.cancel()

    # ── Auto-revoke task ──────────────────────────────────────────────────────

    @tasks.loop(minutes=10)
    async def _revoke_task(self):
        try:
            await self._check_and_revoke_all()
        except Exception:
            log.exception("Error in collector revoke task")

    @_revoke_task.before_loop
    async def _before_revoke(self):
        await self.bot.wait_until_ready()

    async def _check_and_revoke_all(self):
        """
        Check every PlayerCollectorCard.
        Revoke if the requirement no longer exists OR the player owns fewer than required
        (excluding the awarded collector instance from the count).
        DMs the player on each revocation.
        """
        holders = await PlayerCollectorCard.all().prefetch_related(
            "player", "card", "ball"
        )
        to_notify: list[tuple[Player, CollectorCard, Ball]] = []

        for holder in holders:
            should_revoke = False
            try:
                req = await CollectorRequirement.get(
                    card_id=holder.card_id, ball_id=holder.ball_id
                )
                count = await get_player_count(
                    holder.player,
                    holder.ball,
                    exclude_instance_id=holder.ball_instance_id,
                )
                if count < req.count:
                    should_revoke = True
            except DoesNotExist:
                should_revoke = True

            if not should_revoke:
                continue

            if holder.ball_instance_id:
                inst = await BallInstance.get_or_none(pk=holder.ball_instance_id)
                if inst:
                    inst.deleted = True
                    await inst.save(update_fields=["deleted"])

            await holder.delete()
            to_notify.append((holder.player, holder.card, holder.ball))
            log.info(
                f"Revoked {holder.card.name} collector card for {holder.ball.country} "
                f"from player {holder.player.discord_id}"
            )

        for player, card, ball in to_notify:
            try:
                user = await self.bot.fetch_user(player.discord_id)
                tier_em = f"{card.emoji} " if card.emoji else ""
                await user.send(
                    f"⚠️ Your **{tier_em}{card.name}** collector card for "
                    f"**{ball.country}** has been revoked — you no longer own enough.\n"
                    f"Collect more and use `/collector claim` to earn it back!"
                )
            except discord.HTTPException:
                pass

    # ── Player commands ───────────────────────────────────────────────────────

    @app_commands.command()
    async def list(self, interaction: Interaction):
        """See every collectible's collector card thresholds, sorted by rarity."""
        await interaction.response.defer()

        tiers = await CollectorCard.filter(enabled=True).order_by("name").all()
        if not tiers:
            await interaction.followup.send(
                "No collector tiers have been configured yet.", ephemeral=True
            )
            return

        ball_reqs: dict[int, dict[int, int]] = {}
        for req in await (
            CollectorRequirement.filter(card__enabled=True)
            .prefetch_related("ball", "card")
            .all()
        ):
            ball_reqs.setdefault(req.ball_id, {})[req.card_id] = req.count

        if not ball_reqs:
            await interaction.followup.send(
                "No requirements have been configured yet.", ephemeral=True
            )
            return

        tier_header = "  ".join(
            f"{t.emoji + ' ' if t.emoji else ''}{t.name}" for t in tiers
        )

        entries: list[tuple[Ball, str]] = []
        for ball_id, card_counts in ball_reqs.items():
            ball = balls.get(ball_id)
            if not ball:
                ball = await Ball.get_or_none(pk=ball_id)
                if not ball:
                    continue
            parts = [
                f"{t.emoji + ' ' if t.emoji else ''}{t.name}: **{card_counts[t.id]:,}**"
                for t in tiers
                if t.id in card_counts
            ]
            if parts:
                entries.append((ball, " · ".join(parts)))

        entries.sort(key=lambda x: x[0].rarity)

        total_pages = max(1, (len(entries) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        pages: list[discord.Embed] = []
        for i in range(0, max(1, len(entries)), ITEMS_PER_PAGE):
            chunk = entries[i : i + ITEMS_PER_PAGE]
            embed = discord.Embed(
                title="🏅 Collector Card Requirements",
                description=f"Tiers: {tier_header}",
                color=discord.Color.gold(),
            )
            for ball, req_line in chunk:
                embed.add_field(
                    name=f"{ball_emoji(ball, self.bot)} {ball.country}",
                    value=req_line,
                    inline=False,
                )
            embed.set_footer(text=f"Page {len(pages) + 1}/{total_pages} • Sorted by rarity")
            pages.append(embed)

        if len(pages) == 1:
            await interaction.followup.send(embed=pages[0])
        else:
            view = CollectorListView(interaction, pages)
            await interaction.followup.send(embed=pages[0], view=view)

    @app_commands.command()
    @app_commands.describe(collectible="The collectible to view collector tiers for")
    async def info(self, interaction: Interaction, collectible: CollectorBallTransform):
        """See all collector tiers available for a specific collectible and your progress."""
        await interaction.response.defer()

        player = await get_or_create_player(interaction.user.id)

        reqs = (
            await CollectorRequirement.filter(ball=collectible, card__enabled=True)
            .prefetch_related("card")
            .order_by("count")
            .all()
        )
        if not reqs:
            await interaction.followup.send(
                f"No collector tiers are configured for **{collectible.country}**."
            )
            return

        owned = await get_player_count(player, collectible)
        claimed_card_ids = set(
            await PlayerCollectorCard.filter(
                player=player, ball=collectible
            ).values_list("card_id", flat=True)
        )

        embed = discord.Embed(
            title=f"{ball_emoji(collectible, self.bot)} {collectible.country} — Collector Tiers",
            description=f"You own: **{owned:,}** {collectible.country}",
            color=discord.Color.gold(),
        )
        for req in reqs:
            card = req.card
            tier_em = f"{card.emoji} " if card.emoji else ""
            if req.card_id in claimed_card_ids:
                status = "✅ Claimed"
            elif owned >= req.count:
                status = "🟡 Ready to claim! Use `/collector claim`"
            else:
                status = f"❌ Need **{req.count - owned:,}** more"
            embed.add_field(
                name=f"{tier_em}{card.name}",
                value=f"Requires: **{req.count:,}** · {status}",
                inline=False,
            )

        await interaction.followup.send(embed=embed)

    @app_commands.command()
    @app_commands.describe(
        collectible="The collectible you want to claim a card for",
        card="The collector tier to claim",
    )
    async def claim(
        self,
        interaction: Interaction,
        collectible: CollectorBallTransform,
        card: CollectorCardTransform,
    ):
        """Claim a collector card tier for a specific collectible."""
        await interaction.response.defer(ephemeral=True)

        tier_em = f"{card.emoji} " if card.emoji else ""

        if not card.special_id:
            await interaction.followup.send(
                f"**{tier_em}{card.name}** doesn't have a special background set up yet. "
                f"Contact an admin!",
                ephemeral=True,
            )
            return

        player = await get_or_create_player(interaction.user.id)

        already = await PlayerCollectorCard.filter(
            player=player, card=card, ball=collectible
        ).exists()
        if already:
            await interaction.followup.send(
                f"You already own the **{tier_em}{card.name}** card for "
                f"**{collectible.country}**!",
                ephemeral=True,
            )
            return

        try:
            req = await CollectorRequirement.get(card=card, ball=collectible)
        except DoesNotExist:
            await interaction.followup.send(
                f"**{tier_em}{card.name}** has no threshold set for "
                f"**{collectible.country}**. Contact an admin!",
                ephemeral=True,
            )
            return

        owned = await get_player_count(player, collectible)
        if owned < req.count:
            await interaction.followup.send(
                f"You need **{req.count - owned:,}** more **{collectible.country}** "
                f"to claim **{tier_em}{card.name}**!\n"
                f"You have: **{owned:,}** / **{req.count:,}**",
                ephemeral=True,
            )
            return

        new_instance = await BallInstance.create(
            player=player,
            ball=collectible,
            special_id=card.special_id,
            attack_bonus=0,
            health_bonus=0,
            tradeable=False,
        )

        try:
            await PlayerCollectorCard.create(
                player=player,
                card=card,
                ball=collectible,
                ball_instance=new_instance,
            )
        except IntegrityError:
            # Race condition: another request claimed it simultaneously — clean up
            await new_instance.delete()
            await interaction.followup.send(
                f"You already own the **{tier_em}{card.name}** card for "
                f"**{collectible.country}**!",
                ephemeral=True,
            )
            return

        log.info(
            f"Player {player.discord_id} claimed {card.name} collector card "
            f"for {collectible.country} (instance #{new_instance.pk})"
        )
        await interaction.followup.send(
            f"🎉 Congratulations! You claimed the **{tier_em}{card.name}** "
            f"collector card for **{collectible.country}**!"
        )

    @app_commands.command()
    async def mycards(self, interaction: Interaction):
        """See all collector cards you currently own."""
        await interaction.response.defer(ephemeral=True)

        player = await get_or_create_player(interaction.user.id)
        owned = (
            await PlayerCollectorCard.filter(player=player)
            .prefetch_related("card", "ball")
            .order_by("ball__rarity", "card__name")
            .all()
        )
        if not owned:
            await interaction.followup.send(
                "You don't own any collector cards yet!\n"
                "Use `/collector list` to see what's available and "
                "`/collector info` to track your progress."
            )
            return

        embed = discord.Embed(
            title=f"🏅 {interaction.user.display_name}'s Collector Cards",
            color=discord.Color.gold(),
        )
        for holder in owned:
            card = holder.card
            ball = balls.get(holder.ball_id) or holder.ball
            tier_em = f"{card.emoji} " if card.emoji else ""
            embed.add_field(
                name=f"{ball_emoji(ball, self.bot)} {ball.country} — {tier_em}{card.name}",
                value=f"Claimed <t:{int(holder.claimed_at.timestamp())}:R>",
                inline=True,
            )
        await interaction.followup.send(embed=embed)

    @app_commands.command()
    @app_commands.describe(
        collectible="The collectible to check your collector progress for"
    )
    async def check(self, interaction: Interaction, collectible: CollectorBallTransform):
        """Check your collector card progress for a specific collectible."""
        await interaction.response.defer(ephemeral=True)

        player = await get_or_create_player(interaction.user.id)
        reqs = (
            await CollectorRequirement.filter(ball=collectible, card__enabled=True)
            .prefetch_related("card")
            .order_by("count")
            .all()
        )
        if not reqs:
            await interaction.followup.send(
                f"No collector tiers are configured for **{collectible.country}**."
            )
            return

        owned = await get_player_count(player, collectible)
        claimed_card_ids = set(
            await PlayerCollectorCard.filter(
                player=player, ball=collectible
            ).values_list("card_id", flat=True)
        )

        lines: list[str] = []
        for req in reqs:
            card = req.card
            tier_em = f"{card.emoji} " if card.emoji else ""
            if req.card_id in claimed_card_ids:
                lines.append(f"✅ **{tier_em}{card.name}** — already claimed")
            elif owned >= req.count:
                lines.append(
                    f"🟡 **{tier_em}{card.name}** — ready! "
                    f"({owned:,}/{req.count:,}) Use `/collector claim`"
                )
            else:
                lines.append(
                    f"❌ **{tier_em}{card.name}** — "
                    f"{owned:,}/{req.count:,} (need **{req.count - owned:,}** more)"
                )

        embed = discord.Embed(
            title=f"{ball_emoji(collectible, self.bot)} {collectible.country} — Your Progress",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"You own {owned:,} {collectible.country}")
        await interaction.followup.send(embed=embed)

    @app_commands.command()
    async def leaderboard(self, interaction: Interaction):
        """See who has claimed the most collector cards."""
        await interaction.response.defer()

        holders = await PlayerCollectorCard.all().prefetch_related("player")
        counts: dict[int, int] = {}
        for holder in holders:
            did = holder.player.discord_id
            counts[did] = counts.get(did, 0) + 1

        if not counts:
            await interaction.followup.send(
                "Nobody has claimed a collector card yet! "
                "Use `/collector list` to see what's available."
            )
            return

        sorted_players = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        medals = ["🥇", "🥈", "🥉"]
        lines: list[str] = []

        for i, (discord_id, count) in enumerate(sorted_players[:10]):
            medal = medals[i] if i < 3 else f"`#{i + 1}`"
            user = self.bot.get_user(discord_id)
            if user is None:
                try:
                    user = await self.bot.fetch_user(discord_id)
                except discord.HTTPException:
                    lines.append(f"{medal} Unknown user — {count} card(s)")
                    continue
            noun = "card" if count == 1 else "cards"
            lines.append(f"{medal} **{user.display_name}** — {count} {noun}")

        embed = discord.Embed(
            title="🏅 Collector Leaderboard",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        await interaction.followup.send(embed=embed)
