"""Tool-specific minimal patch applicators for SceneRepair.ops."""

from educast.reviewloop.repair_apply.common import ApplyResult
from educast.reviewloop.repair_apply.image_ops import apply_image_ops, prompt_addendum_from_ops
from educast.reviewloop.repair_apply.interactive_ops import apply_interactive_ops
from educast.reviewloop.repair_apply.manim_ops import apply_manim_ops
from educast.reviewloop.repair_apply.remotion_ops import apply_remotion_ops

__all__ = [
    "ApplyResult",
    "apply_image_ops",
    "apply_interactive_ops",
    "apply_manim_ops",
    "apply_remotion_ops",
    "prompt_addendum_from_ops",
]
