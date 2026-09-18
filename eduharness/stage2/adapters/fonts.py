"""Locate a TrueType font for the style's font family (Pillow needs a file path)."""

from __future__ import annotations

import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

_CANDIDATES = {
    False: (
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ),
    True: (
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ),
}


@lru_cache(maxsize=32)
def find_font_file(family: str, bold: bool = False) -> Path | None:
    if family.strip().casefold() == "inter":
        filename = "Inter-Bold.ttf" if bold else "Inter-Regular.ttf"
        bundled = Path(__file__).resolve().parents[2] / "assets/fonts/inter" / filename
        if bundled.is_file():
            return bundled
    if shutil.which("fc-match"):
        pattern = f"{family}:bold" if bold else family
        try:
            out = subprocess.check_output(
                ["fc-match", "-f", "%{file}", pattern], text=True, timeout=10
            ).strip()
            if out and out.lower().endswith((".ttf", ".otf")) and Path(out).is_file():
                return Path(out)
        except Exception:
            pass
    for candidate in _CANDIDATES[bold]:
        if Path(candidate).is_file():
            return Path(candidate)
    return None


def load_font(family: str, size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = find_font_file(family, bold)
    if path is not None:
        try:
            return ImageFont.truetype(str(path), max(8, int(size)))
        except Exception:
            pass
    try:
        return ImageFont.load_default(size=max(8, int(size)))  # Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()
