"""Tool-specific minimal patch applicators for SceneRepair.ops."""

from .common import ApplyResult
from .image_ops import apply_image_ops, prompt_addendum_from_ops
from .interactive_ops import apply_interactive_ops
from .manim_ops import apply_manim_ops
from .remotion_ops import apply_remotion_ops

__all__ = [
    "ApplyResult",
    "apply_image_ops",
    "apply_interactive_ops",
    "apply_manim_ops",
    "apply_remotion_ops",
    "prompt_addendum_from_ops",
]
