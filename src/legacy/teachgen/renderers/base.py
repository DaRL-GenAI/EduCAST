"""SegmentRenderer protocol + a tiny registry keyed by Modality."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..config import Config
from ..providers.base import Provider
from ..schema import Modality, Segment, VisualAsset


@dataclass
class RenderContext:
    """Everything a renderer needs that isn't in the Segment itself."""

    cfg: Config
    provider: Provider
    out_dir: Path                      # where to write this segment's visual
    audio_seconds: float | None = None  # narration duration, if already known


@runtime_checkable
class SegmentRenderer(Protocol):
    modality: Modality

    def render(self, seg: Segment, ctx: RenderContext) -> VisualAsset:
        """Produce the visual for one segment and return a normalized VisualAsset."""
        ...


REGISTRY: dict[Modality, SegmentRenderer] = {}


def register(renderer: SegmentRenderer) -> None:
    REGISTRY[renderer.modality] = renderer


def get_renderer(modality: Modality) -> SegmentRenderer:
    try:
        return REGISTRY[modality]
    except KeyError:
        raise KeyError(f"no renderer registered for modality {modality!r}")
