import os
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

from ballsdex.settings import settings

if TYPE_CHECKING:
    from ballsdex.core.models import BallInstance


SOURCES_PATH = Path(os.path.dirname(os.path.abspath(__file__)), "./src")
WIDTH = 1500
HEIGHT = 2000

RECTANGLE_WIDTH = WIDTH - 40
RECTANGLE_HEIGHT = (HEIGHT // 5) * 2

CORNERS = ((34, 261), (1393, 992))
artwork_size = [b - a for a, b in zip(*CORNERS)]

title_font = ImageFont.truetype(str(SOURCES_PATH / "ArsenicaTrial-Extrabold.ttf"), 170)
capacity_name_font = ImageFont.truetype(str(SOURCES_PATH / "Bobby Jones Soft.otf"), 110)
capacity_description_font = ImageFont.truetype(str(SOURCES_PATH / "OpenSans-Semibold.ttf"), 75)
stats_font = ImageFont.truetype(str(SOURCES_PATH / "Bobby Jones Soft.otf"), 130)
credits_font = ImageFont.truetype(str(SOURCES_PATH / "arial.ttf"), 40)

credits_color_cache: dict = {}

_ball_styles: dict[int, dict] = {}


async def refresh_card_style() -> None:
    global _ball_styles
    try:
        from tortoise import Tortoise
        conn = Tortoise.get_connection("default")
        rows = await conn.execute_query_dict(
            """
            SELECT cs.*, csb.ball_id
            FROM card_style_cardstyle cs
            JOIN card_style_cardstyle_balls csb ON cs.id = csb.cardstyle_id
            ORDER BY cs.updated_at DESC
            """
        )
        mapping: dict[int, dict] = {}
        for row in rows:
            ball_id = row["ball_id"]
            if ball_id not in mapping:
                mapping[ball_id] = row
        _ball_styles = mapping
    except Exception:
        _ball_styles = {}


def _hex_to_rgba(hex_str: str, alpha: int = 255) -> tuple:
    h = hex_str.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (r, g, b, alpha)


def _make_gradient(
    size: tuple[int, int],
    color1: tuple,
    color2: tuple,
    direction: str,
) -> Image.Image:
    w, h = size
    gradient = Image.new("RGBA", size)
    draw = ImageDraw.Draw(gradient)

    def lerp(t: float) -> tuple:
        return tuple(int(color1[i] * (1.0 - t) + color2[i] * t) for i in range(4))  # type: ignore

    if direction == "vertical":
        for y in range(h):
            draw.line([(0, y), (w, y)], fill=lerp(y / max(h - 1, 1)))
    elif direction == "diagonal":
        for x in range(w):
            for y in range(h):
                t = (x / max(w - 1, 1) + y / max(h - 1, 1)) / 2
                gradient.putpixel((x, y), lerp(t))
    else:
        for x in range(w):
            draw.line([(x, 0), (x, h)], fill=lerp(x / max(w - 1, 1)))
    return gradient


def _text_mask(
    canvas_size: tuple[int, int],
    position: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    stroke_width: int = 0,
    anchor: str | None = None,
) -> Image.Image:
    mask = Image.new("L", canvas_size, 0)
    d = ImageDraw.Draw(mask)
    kw: dict[str, Any] = {"font": font, "fill": 255}
    if stroke_width:
        kw["stroke_width"] = stroke_width
        kw["stroke_fill"] = 255
    if anchor:
        kw["anchor"] = anchor
    d.text(position, text, **kw)
    return mask


def _draw_styled_text(
    image: Image.Image,
    position: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    color: str,
    gradient_end: str = "",
    gradient_dir: str = "horizontal",
    stroke_width: int = 0,
    stroke_color: str = "#000000",
    glow_radius: int = 0,
    glow_color: str = "#FFFFFF",
    anchor: str | None = None,
) -> None:
    size = image.size
    draw = ImageDraw.Draw(image)
    use_gradient = bool(gradient_end and len(gradient_end) == 7)
    kw_anchor: dict[str, Any] = {"anchor": anchor} if anchor else {}

    if glow_radius > 0:
        glow_rgba = _hex_to_rgba(glow_color, 255)
        glow_src = Image.new("RGBA", size, (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow_src)
        glow_draw.text(position, text, font=font, fill=glow_rgba, **kw_anchor)
        blurred = glow_src.filter(ImageFilter.GaussianBlur(radius=glow_radius))
        for _ in range(5):
            image.alpha_composite(blurred)

    if not use_gradient:
        draw.text(
            position,
            text,
            font=font,
            fill=_hex_to_rgba(color),
            stroke_width=stroke_width,
            stroke_fill=_hex_to_rgba(stroke_color) if stroke_width else None,
            **kw_anchor,
        )
        return

    bbox = draw.textbbox(position, text, font=font, **kw_anchor)
    bx0, by0, bx1, by1 = bbox
    bw, bh = max(bx1 - bx0, 1), max(by1 - by0, 1)

    c1 = _hex_to_rgba(color)
    c2 = _hex_to_rgba(gradient_end)
    grad_patch = _make_gradient((bw, bh), c1, c2, gradient_dir)

    if stroke_width > 0:
        stroke_mask = _text_mask(size, position, text, font,
                                 stroke_width=stroke_width, anchor=anchor)
        text_mask = _text_mask(size, position, text, font,
                               stroke_width=0, anchor=anchor)
        stroke_only = ImageChops.subtract(stroke_mask, text_mask)

        stroke_layer = Image.new("RGBA", size, (0, 0, 0, 0))
        stroke_rgba = _hex_to_rgba(stroke_color)
        stroke_color_img = Image.new("RGBA", size, stroke_rgba)
        stroke_layer.paste(stroke_color_img, mask=stroke_only)
        image.alpha_composite(stroke_layer)
    else:
        text_mask = _text_mask(size, position, text, font,
                               stroke_width=0, anchor=anchor)

    cropped_mask = text_mask.crop((bx0, by0, bx1, by1))
    grad_layer = Image.new("RGBA", size, (0, 0, 0, 0))
    grad_layer.paste(grad_patch, (bx0, by0), mask=cropped_mask)
    image.alpha_composite(grad_layer)


def _gs(style: dict | None, prefix: str, attr: str, default: Any) -> Any:
    if style is None:
        return default
    val = style.get(f"{prefix}_{attr}")
    if val is None:
        return default
    return val


def get_credit_color(image: Image.Image, region: tuple) -> tuple:
    image = image.crop(region)
    brightness = sum(image.convert("L").getdata()) / image.width / image.height  # type: ignore
    return (0, 0, 0, 255) if brightness > 100 else (255, 255, 255, 255)


def draw_card(
    ball_instance: "BallInstance",
    media_path: str = "./admin_panel/media/",
) -> tuple[Image.Image, dict[str, Any]]:
    ball = ball_instance.countryball
    ball_credits = ball.credits
    special_credits = ""
    card_name = ball.cached_regime.name
    if special_image := ball_instance.special_card:
        card_name = getattr(ball_instance.specialcard, "name", card_name)
        image = Image.open(media_path + special_image)
        if ball_instance.specialcard and ball_instance.specialcard.credits:
            special_credits += f" • Special Author: {ball_instance.specialcard.credits}"
    else:
        image = Image.open(media_path + ball.cached_regime.background)
    image = image.convert("RGBA")
    icon = (
        Image.open(media_path + ball.cached_economy.icon).convert("RGBA")
        if ball.cached_economy
        else None
    )

    ball_style = _ball_styles.get(ball.pk)

    def s(prefix: str, attr: str, default: Any) -> Any:
        return _gs(ball_style, prefix, attr, default)

    _draw_styled_text(
        image, (50, 20),
        ball.short_name or ball.country,
        title_font,
        color=s("title", "color", "#FFFFFF"),
        gradient_end=s("title", "gradient_end", ""),
        gradient_dir=s("title", "gradient_dir", "horizontal"),
        stroke_width=s("title", "stroke_width", 2),
        stroke_color=s("title", "stroke_color", "#000000"),
        glow_radius=s("title", "glow_radius", 0),
        glow_color=s("title", "glow_color", "#FFFFFF"),
    )

    cap_name = textwrap.wrap(f"Ability: {ball.capacity_name}", width=26)
    for i, line in enumerate(cap_name):
        _draw_styled_text(
            image, (100, 1050 + 100 * i),
            line,
            capacity_name_font,
            color=s("ability_name", "color", "#E6E6E6"),
            gradient_end=s("ability_name", "gradient_end", ""),
            gradient_dir=s("ability_name", "gradient_dir", "horizontal"),
            stroke_width=s("ability_name", "stroke_width", 2),
            stroke_color=s("ability_name", "stroke_color", "#000000"),
            glow_radius=s("ability_name", "glow_radius", 0),
            glow_color=s("ability_name", "glow_color", "#FFFFFF"),
        )

    cap_desc_lines = list(
        wrapped
        for newline in ball.capacity_description.splitlines()
        for wrapped in textwrap.wrap(newline, 32)
    )
    for i, line in enumerate(cap_desc_lines):
        _draw_styled_text(
            image, (60, 1100 + 100 * len(cap_name) + 80 * i),
            line,
            capacity_description_font,
            color=s("ability_desc", "color", "#FFFFFF"),
            gradient_end=s("ability_desc", "gradient_end", ""),
            gradient_dir=s("ability_desc", "gradient_dir", "horizontal"),
            stroke_width=s("ability_desc", "stroke_width", 1),
            stroke_color=s("ability_desc", "stroke_color", "#000000"),
            glow_radius=s("ability_desc", "glow_radius", 0),
            glow_color=s("ability_desc", "glow_color", "#FFFFFF"),
        )

    _draw_styled_text(
        image, (320, 1670),
        str(ball_instance.health),
        stats_font,
        color=s("health", "color", "#ED7365"),
        gradient_end=s("health", "gradient_end", ""),
        gradient_dir=s("health", "gradient_dir", "horizontal"),
        stroke_width=s("health", "stroke_width", 1),
        stroke_color=s("health", "stroke_color", "#000000"),
        glow_radius=s("health", "glow_radius", 0),
        glow_color=s("health", "glow_color", "#FF0000"),
    )

    _draw_styled_text(
        image, (1120, 1670),
        str(ball_instance.attack),
        stats_font,
        color=s("attack", "color", "#FCC24C"),
        gradient_end=s("attack", "gradient_end", ""),
        gradient_dir=s("attack", "gradient_dir", "horizontal"),
        stroke_width=s("attack", "stroke_width", 1),
        stroke_color=s("attack", "stroke_color", "#000000"),
        glow_radius=s("attack", "glow_radius", 0),
        glow_color=s("attack", "glow_color", "#FFD700"),
        anchor="ra",
    )

    if settings.show_rarity:
        draw = ImageDraw.Draw(image)
        draw.text(
            (1200, 50),
            str(ball.rarity),
            font=stats_font,
            stroke_width=2,
            stroke_fill=(0, 0, 0, 255),
        )

    credits_text = (
        f"Created by El Laggron{special_credits}\n"
        f"Artwork author: {ball_credits}"
    )

    if s("credits", "auto_color", True):
        if card_name in credits_color_cache:
            credits_rgba = credits_color_cache[card_name]
        else:
            credits_rgba = get_credit_color(
                image, (0, int(image.height * 0.8), image.width, image.height)
            )
            credits_color_cache[card_name] = credits_rgba
        credits_hex = "#{:02X}{:02X}{:02X}".format(*credits_rgba[:3])
    else:
        credits_hex = s("credits", "color", "#FFFFFF")

    _draw_styled_text(
        image, (30, 1870),
        credits_text,
        credits_font,
        color=credits_hex,
        gradient_end=s("credits", "gradient_end", ""),
        gradient_dir=s("credits", "gradient_dir", "horizontal"),
        stroke_width=s("credits", "stroke_width", 0),
        stroke_color=s("credits", "stroke_color", "#000000"),
        glow_radius=s("credits", "glow_radius", 0),
        glow_color=s("credits", "glow_color", "#FFFFFF"),
    )

    artwork = Image.open(media_path + ball.collection_card).convert("RGBA")
    image.paste(ImageOps.fit(artwork, artwork_size), CORNERS[0])  # type: ignore

    if icon:
        icon = ImageOps.fit(icon, (192, 192))
        image.paste(icon, (1200, 30), mask=icon)
        icon.close()
    artwork.close()

    return image, {"format": "WEBP"}
