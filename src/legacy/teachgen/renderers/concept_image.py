"""`concept_image` renderer — wraps teachgen's concept_image.py two-step flow.

We reuse concept_image's exact prompt-engineering (a GPT writes a rich English
image prompt) but route both calls through teachgen's Provider so the whole system
still needs only one key. Static output: kind="image".
"""

from __future__ import annotations

from ..schema import Modality, Segment, VisualAsset
from .base import RenderContext
from .. import concept_image as ci  # the standalone helper, now a teachgen module


_STYLE = (
    "visually stunning educational infographic in a clean, modern academic style; "
    "soft neutral background (cream or light beige); "
    "elegant serif typography for section titles, minimalist sans-serif for body text; "
    "layout organized into clearly separated numbered sections (1, 2, 3, 4), each with a "
    "concise heading and short explanation; subtle dividing lines and balanced spacing; "
    "mathematical notation, symbols, and step-by-step visual diagrams (grids, arrows, "
    "highlights, boxed elements) to illustrate concepts clearly; "
    "limited color palette: teal accents, gold highlights, dark gray text on cream ground; "
    "arrows, dotted lines, or highlighted boxes to guide the viewer through the logic; "
    "symmetry, alignment, and a polished 'textbook meets modern design' aesthetic; "
    "premium educational poster — minimal, elegant, highly readable, intellectually satisfying"
)


class ConceptImageRenderer:
    modality = Modality.CONCEPT_IMAGE

    def render(self, seg: Segment, ctx: RenderContext) -> VisualAsset:
        # Step 1: expand the brief into a detailed English image prompt.
        image_prompt = ctx.provider.chat(
            ci.build_user_brief(seg.visual_brief, ctx.cfg.audience, _STYLE),
            system=ci.PROMPT_SYSTEM,
            max_tokens=800,
        )
        # Step 2: render it. concept_image targets 3:2 landscape for slide framing.
        png = ctx.provider.image(image_prompt, size="1536x1024", quality="high")

        png_path = ctx.out_dir / f"{seg.id}.png"
        png_path.write_bytes(png)
        return VisualAsset(segment_id=seg.id, kind="image", path=str(png_path))
