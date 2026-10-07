from __future__ import annotations

from pathlib import Path


SOURCES_PATH = Path(__file__).resolve().parent / "src"

# The first option intentionally preserves the original NBADex typography.
FONT_CHOICES = [
    ("default", "Original NBADex fonts (default)"),
    ("roboto_condensed", "Roboto Condensed — screenshot-style condensed"),
    ("bebas_neue", "Bebas Neue — bold sports headline"),
    ("anton", "Anton — strong poster headline"),
    ("oswald", "Oswald — clean condensed"),
    ("barlow_condensed", "Barlow Condensed — modern athletic"),
    ("rajdhani", "Rajdhani — sharp futuristic"),
    ("teko", "Teko — tall display"),
    ("orbitron", "Orbitron — sci-fi geometric"),
    ("audiowide", "Audiowide — wide futuristic"),
    ("black_ops_one", "Black Ops One — impact display"),
    ("exo_2", "Exo 2 — polished tech"),
    ("space_grotesk", "Space Grotesk — premium geometric"),
    ("cinzel", "Cinzel — classic monumental"),
]

FONT_FILES = {
    "roboto_condensed": "RobotoCondensed[wght].ttf",
    "bebas_neue": "BebasNeue-Regular.ttf",
    "anton": "Anton-Regular.ttf",
    "oswald": "Oswald[wght].ttf",
    "barlow_condensed": "BarlowCondensed-SemiBold.ttf",
    "rajdhani": "Rajdhani-SemiBold.ttf",
    "teko": "Teko[wght].ttf",
    "orbitron": "Orbitron[wght].ttf",
    "audiowide": "Audiowide-Regular.ttf",
    "black_ops_one": "BlackOpsOne-Regular.ttf",
    "exo_2": "Exo2[wght].ttf",
    "space_grotesk": "SpaceGrotesk[wght].ttf",
    "cinzel": "Cinzel[wght].ttf",
}


def font_path(font_family: str) -> Path | None:
    filename = FONT_FILES.get(font_family)
    if filename is None:
        return None
    path = SOURCES_PATH / filename
    return path if path.is_file() else None