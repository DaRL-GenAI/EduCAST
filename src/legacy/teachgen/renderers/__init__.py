"""Renderer plugins — the swappable production paths.

Importing this package registers the built-in renderers. To add a fourth path:
write a class with a `modality` attribute and a `render(seg, ctx)` method, then
call `register(YourRenderer())` here. Nothing else in the pipeline changes.
"""

from __future__ import annotations

from .base import REGISTRY, RenderContext, SegmentRenderer, get_renderer, register


def _install_builtins() -> None:
    from .animation import AnimationRenderer
    from .concept_image import ConceptImageRenderer
    from .slide import SlideRenderer

    register(SlideRenderer())
    register(ConceptImageRenderer())
    register(AnimationRenderer())


_install_builtins()

__all__ = ["REGISTRY", "RenderContext", "SegmentRenderer", "get_renderer", "register"]
