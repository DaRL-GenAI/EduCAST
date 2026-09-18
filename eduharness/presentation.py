"""Deterministic presentation-template helpers shared by local renderers."""

from __future__ import annotations

import hashlib
from pathlib import Path


CHARACTER_COUNT = 3

# The opener's cast leans in from the two bottom corners. These ratios are the
# Python half of a pair: `TITLE_CAST_*` in remotion_template/src/SceneBeat.tsx
# holds the same numbers for the browser renderer, and the Pillow fallback below
# reproduces the same still, so a missing Chrome never changes the composition.
TITLE_CAST = {"left": (1, 2), "right": (4, 3)}
TITLE_CAST_HEIGHT_RATIO = 0.52   # character height, as a share of the frame
TITLE_CAST_ASPECT = 0.62         # the character art is ~430x700
TITLE_CAST_SUBMERGE = 0.17       # share of each body that stays below the frame
TITLE_CAST_HUG = 0.36            # shoulder overlap, so neighbours touch
TITLE_CAST_CORNER_BITE = 0.2     # how far the outermost one leans past the edge


def character_index(scene_id: str) -> int:
    """Pick one of the three homepage characters without using Python's random hash."""
    digest = hashlib.sha256(str(scene_id).encode("utf-8")).digest()
    return digest[0] % CHARACTER_COUNT + 1


def character_path(scene_id: str) -> Path:
    root = Path(__file__).resolve().parent / "studio" / "assets" / "characters"
    return root / f"character-{character_index(scene_id)}.png"


def character_asset_path(scene_id: str) -> Path:
    """Alias used by render adapters to make the intent explicit."""
    return character_path(scene_id)


def character_asset(number: int) -> Path:
    """One specific character sheet, by the number the templates address it with."""
    root = Path(__file__).resolve().parent / "studio" / "assets" / "characters"
    return root / f"character-{int(number)}.png"


def title_cast() -> dict[str, tuple[int, ...]]:
    """Which characters stand in which bottom corner of the opener."""
    return {side: tuple(numbers) for side, numbers in TITLE_CAST.items()}
