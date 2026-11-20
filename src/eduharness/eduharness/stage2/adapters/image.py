"""Two-step concept images: expand a teaching brief, then generate the whole diagram.

The lesson has exactly three visual contracts:

1. the opener — a Remotion-only stage with its own hard-coded layout (see
   ``remotion.render_fallback_slide`` and remotion_template/src/SceneBeat.tsx);
2. image scenes — a text model writes the prompt, ``gpt-image`` draws the whole
   diagram, and ``compose_concept_image`` drops that art into ``regions.main``
   of the shared teaching board (no cover-crop, no palette snap);
3. every other Manim/Remotion scene — the same board, drawn by its own renderer.

``draw_teaching_board`` and the text helpers below are the board's raster half;
``compose_final(brief=None)`` is the pre-board compositor, kept only so image
checkpoints prepared by older runs still render.
"""

from __future__ import annotations

import colorsys
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from ...providers.base import Provider
from ...presentation import character_asset_path
from ...schema import (
    SceneBrief,
    SceneRepair,
    StyleConfig,
    teaching_board,
)
from ..repair_apply.image_ops import prompt_addendum_from_ops
from .fonts import load_font


PROMPT_SYSTEM = """\
You are an expert visual-explainer and art director. Given a teaching concept,
write ONE detailed English prompt for a text-to-image model to produce a single
polished, presentation-ready educational illustration (a slide-sized diagram).

Specify the core idea and key labelled parts, a clear left-to-right or top-to-bottom
flow with arrows when useful, and concrete simple iconography or metaphors.
Use one central visual idea, generous whitespace, and at most 3-5 short labels
(1-3 words each). Quote the exact labels in the requested teaching language.
No paragraphs, long bullet lists, tiny captions, dense multi-panel posters, or
decorative extras. Use a modern flat-vector/clean-infographic style, restrained
teal/gold/dark-gray palette, rounded shapes, and a light cream or white background.
Specify landscape 3:2 composition suitable for a teaching slide, no photorealism,
no watermark, and comfortable safe margins around every label and object.

Produce a complete teaching diagram with its own labels. Older briefs may request
text-free art, locally added captions, an isolated art asset, or a fixed board/grid:
replace those presentation instructions with this complete concept-image format.
Preserve the teaching meaning and all required visible elements. Keep scientific
relationships accurate; do not invent numerical values or unsupported conclusions.
Use the narration to resolve ambiguity in the visual brief.
Output ONLY the final image prompt as a single English paragraph, no preamble,
quotes around the paragraph, or markdown.
"""


def _is_light(hex_color: str) -> bool:
    v = hex_color.lstrip("#")
    r, g, b = (int(v[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.45


def caption_for(brief: SceneBrief) -> str:
    text = (brief.caption or "").strip()
    return text[:160] if text else ""


def build_prompt(
    brief: SceneBrief,
    style: StyleConfig,
    *,
    repair: SceneRepair | None = None,
    feedback: str = "",
    audience: str = "general learners",
    language: str = "English",
) -> str:
    """Build the content brief for the prompt-writing model (not the image API)."""
    elements = "; ".join(brief.key_elements)
    prompt = (
        f"Concept to illustrate: {brief.title}\n"
        f"Visual brief: {brief.visual_brief.strip()}\n"
        f"Narration: {brief.narration}\n"
        f"Teaching takeaway: {brief.takeaway or brief.caption}\n"
        f"Must clearly show: {elements}\n"
        f"Target audience: {audience}\n"
        f"Teaching language for the image labels: {language}\n"
        "Preferred visual style: clean, uncluttered educational illustration; one central "
        "diagram, comparison, metaphor, or flow; teal accents, gold highlights, dark gray "
        "text on cream; large readable short labels and generous whitespace.\n"
        "Produce the detailed English image prompt now."
    )
    if repair and repair.ops:
        addendum = prompt_addendum_from_ops(repair.ops)
        if addendum:
            prompt = f"{prompt} CONSTRAINTS: {addendum}"
    if feedback and not (repair and repair.ops):
        prompt = f"{prompt} FIX FEEDBACK: {feedback}"
    elif repair and repair.fallback_instructions and not repair.ops:
        prompt = f"{prompt} FIX FEEDBACK: {repair.fallback_instructions}"
    return prompt


def generate_prompt(
    provider: Provider,
    brief: SceneBrief,
    style: StyleConfig,
    *,
    repair: SceneRepair | None = None,
    feedback: str = "",
    audience: str = "general learners",
    language: str = "English",
    model: str = "gpt-4o",
) -> str:
    prompt = provider.chat(
        build_prompt(brief, style, repair=repair, feedback=feedback,
                     audience=audience, language=language),
        system=PROMPT_SYSTEM, max_tokens=800, model=model,
    ).strip()
    if not prompt:
        raise ValueError("Concept-image prompt generation returned empty content")
    return prompt


def blend_ground(img: Image.Image, style: StyleConfig, *, near: float = 4.0, far: float = 12.0) -> Image.Image:
    """Fade the art's own flat ground into the board background.

    A concept image arrives on whatever near-white the model chose, so dropping it
    on the board leaves a visible panel edge. Only pixels within ``far`` of that
    ground move, with a ramp from ``near``, so the drawing itself is untouched.

    The ground is read from a ring of border samples rather than the four corners:
    diffusion output is faintly vignetted, so corners that differ by a few levels
    are still one flat ground — insisting they match exactly left the panel edge in.
    """
    image = img.convert("RGB")
    w, h = image.size
    step = max(1, min(w, h) // 32)
    border = ([image.getpixel((x, 0)) for x in range(0, w, step)]
              + [image.getpixel((x, h - 1)) for x in range(0, w, step)]
              + [image.getpixel((0, y)) for y in range(0, h, step)]
              + [image.getpixel((w - 1, y)) for y in range(0, h, step)])
    ground = tuple(sorted(channel)[len(channel) // 2] for channel in zip(*border))
    flat = sum(1 for px in border if max(abs(a - b) for a, b in zip(px, ground)) <= far)
    if flat < 0.75 * len(border):
        return image  # the art bleeds to its edges: no ground to fade
    distance = None
    for channel, level in zip(image.split(), ground):
        delta = ImageChops.difference(channel, Image.new("L", image.size, level))
        distance = delta if distance is None else ImageChops.lighter(distance, delta)
    span = max(1.0, far - near)
    mask = distance.point(lambda d: 255 if d <= near else (0 if d >= far else round(255 * (far - d) / span)))
    return Image.composite(Image.new("RGB", image.size, _hex_rgb(style.palette.background)), image, mask)


def compose_concept_image(
    source: Path,
    out: Path,
    style: StyleConfig,
    *,
    brief: SceneBrief | None = None,
    caption: str = "",
) -> Path:
    """Fit the complete teaching diagram to the player canvas without cropping labels.

    With a brief the diagram is placed inside ``regions.main`` of the same board
    the Manim and Remotion scenes draw, so a still sits in the deck instead of
    replacing it for one section. The art keeps its own colours: palette snapping
    exists for line art that must match the animation hex for hex, and it shreds
    the small labels a concept image draws for itself.
    """
    if brief is not None:
        return compose_final(source, out, style, title=brief.title,
                             caption=caption or brief.takeaway or brief.caption,
                             brief=brief, snap_art=False)
    width, height = style.layout.width, style.layout.height
    with Image.open(source) as src:
        image = src.convert("RGB")
        scale = min(width / image.width, height / image.height)
        fitted = image.resize((max(1, round(image.width * scale)),
                               max(1, round(image.height * scale))), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (width, height), "#FFF8ED")
    canvas.paste(fitted, ((width - fitted.width) // 2, (height - fitted.height) // 2))
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, format="PNG")
    return out


def render_image(
    provider: Provider,
    brief: SceneBrief,
    style: StyleConfig,
    out_path: Path,
    *,
    repair: SceneRepair | None = None,
    feedback: str = "",
    audience: str = "general learners",
    language: str = "English",
    prompt_model: str = "gpt-4o",
) -> Path:
    """One-shot prompt → gpt-image → board, for callers outside the checkpointed
    flow (which drives ``generate_prompt`` / ``provider.image`` /
    ``compose_concept_image`` itself so each half can resume on its own)."""
    prompt = generate_prompt(provider, brief, style, repair=repair, feedback=feedback,
                             audience=audience, language=language, model=prompt_model)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw = out_path.with_name(out_path.stem + "_raw.png")
    provider.image(prompt, str(raw), size="1536x1024")
    out_path.with_name(out_path.stem + "_prompt.txt").write_text(prompt, encoding="utf-8")
    compose_concept_image(raw, out_path, style, brief=brief)
    return out_path




def _box_xywh(box) -> tuple[int, int, int, int]:
    """Accept a schema region mapping or either common four-value box form."""
    if isinstance(box, dict):
        return (round(float(box.get("x", 0))), round(float(box.get("y", 0))),
                round(float(box.get("width", 0))), round(float(box.get("height", 0))))
    values = list(box)
    if len(values) != 4:
        raise ValueError("text box must contain x, y, width, height")
    return tuple(round(float(value)) for value in values)  # type: ignore[return-value]


def _text_lines(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    """Wrap both whitespace-delimited text and scripts without word spaces."""
    lines: list[str] = []
    for paragraph in str(text or "").splitlines() or [""]:
        if not paragraph:
            lines.append("")
            continue
        # Keeping CJK characters individually breakable also handles a long
        # unbroken identifier or URL without losing any semantic text.
        has_spaces = any(char.isspace() for char in paragraph)
        tokens = paragraph.split() if has_spaces else list(paragraph)
        current = ""
        for token in tokens:
            candidate = f"{current} {token}".strip() if has_spaces else current + token
            if current and _measure(draw, candidate, font)[0] <= max_width:
                current = candidate
                continue
            if current:
                lines.append(current)
                current = ""
            if _measure(draw, token, font)[0] > max_width:
                # Split oversized words (URLs, identifiers, or a mixed CJK token)
                # by glyph so no semantic text is silently discarded or clipped.
                piece = ""
                for char in token:
                    trial = piece + char
                    if piece and _measure(draw, trial, font)[0] > max_width:
                        lines.append(piece)
                        piece = char
                    else:
                        piece = trial
                current = piece
            else:
                current = token
        if current:
            lines.append(current)
    return lines or [""]


def draw_fitted_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    box,
    style: StyleConfig,
    *,
    size: int = 32,
    color: str | tuple[int, int, int] | None = None,
    bold: bool = False,
    align: str = "left",
) -> list[str]:
    """Draw all of ``text`` inside a bounded region, shrinking instead of truncating.

    The returned lines are useful to renderer guards and are deliberately kept
    independent of Pillow's private font metrics.  ``box`` is a schema region
    mapping (or ``x, y, width, height`` tuple).  Board regions are left-aligned;
    ``align="center"`` exists for the title card, which is not a board.
    """
    x, y, width, height = _box_xywh(box)
    width, height = max(1, width), max(1, height)
    family = style.typography.font_family
    requested = max(8, int(size))
    chosen_font = load_font(family, requested, bold=bold)
    lines = _text_lines(draw, text, chosen_font, width)
    chosen_size = requested
    # Try progressively smaller type until every line and the whole block fit.
    for candidate_size in range(requested, 7, -1):
        font = load_font(family, candidate_size, bold=bold)
        candidate_lines = _text_lines(draw, text, font, width)
        line_height = max(1, _measure(draw, "Ag", font)[1])
        if (all(_measure(draw, line, font)[0] <= width for line in candidate_lines)
                and len(candidate_lines) * line_height <= height):
            chosen_font, lines, chosen_size = font, candidate_lines, candidate_size
            break
        chosen_font, lines, chosen_size = font, candidate_lines, candidate_size

    fill = _hex_rgb(color) if isinstance(color, str) else (color or _hex_rgb(style.palette.text))
    line_height = max(1, _measure(draw, "Ag", chosen_font)[1])
    # Top-align so neighboring regions remain stable as text gets smaller.
    for index, line in enumerate(lines):
        left = x
        if align == "center":
            left = x + max(0, (width - _measure(draw, line, chosen_font)[0]) // 2)
        draw.text((left, y + index * line_height), line, font=chosen_font, fill=fill)
    return lines


def _common_fitted_text_size(
    draw: ImageDraw.ImageDraw,
    texts: list[str],
    boxes: list[dict],
    style: StyleConfig,
    *,
    size: int,
    bold: bool = False,
) -> int:
    """Return one size that fits every text block in a shared column.

    The board typography is a column-level contract.  Measuring each lecture
    slot independently lets short notes become larger than multiline notes;
    this helper finds the largest size that all slots can use together.
    """
    requested = max(8, int(size))
    for candidate_size in range(requested, 7, -1):
        font = load_font(style.typography.font_family, candidate_size, bold=bold)
        fits = True
        for text, box in zip(texts, boxes):
            _, _, width, height = _box_xywh(box)
            lines = _text_lines(draw, text, font, max(1, width))
            line_height = max(1, _measure(draw, "Ag", font)[1])
            if (not all(_measure(draw, line, font)[0] <= width for line in lines)
                    or len(lines) * line_height > height):
                fits = False
                break
        if fits:
            return candidate_size
    return 7


def draw_teaching_board(
    style: StyleConfig,
    brief: SceneBrief,
    *,
    include_result: bool = True,
    include_character: bool = True,
) -> Image.Image:
    """Create the shared Code2Video-style board with locally rendered text.

    This intentionally contains no generated art.  ``compose_final`` pastes the
    isolated image into ``regions.main``; Remotion can use this function as its
    deterministic raster fallback and add its own visual layer in the same box.
    """
    board = teaching_board(style, brief)
    width, height = int(board["width"]), int(board["height"])
    palette = board["palette"]
    canvas = Image.new("RGB", (width, height), _hex_rgb(palette["background"]))
    draw = ImageDraw.Draw(canvas)
    regions = board["regions"]
    pad = max(8, int(style.layout.padding_px))
    primary, secondary = _hex_rgb(palette["primary"]), _hex_rgb(palette["secondary"])
    text_color, muted = _hex_rgb(palette["text"]), _hex_rgb(palette["muted"])

    # Quiet region framing gives every renderer the same spatial landmarks while
    # keeping the generated art itself free of board chrome.
    title_box = regions["title"]
    tx, ty, tw, th = _box_xywh(title_box)
    draw.rectangle((tx, ty, tx + tw, ty + th), fill=_hex_rgb(palette["background"]))
    draw.rectangle((tx, max(0, ty + th - 5), min(width, tx + max(72, pad * 5)), ty + th), fill=secondary)
    draw_fitted_text(draw, board["title"], title_box, style, size=board["font"]["title"],
                     color=palette["text"], bold=True)

    lecture_box = regions["lecture"]
    lx, ly, lw, lh = _box_xywh(lecture_box)
    draw.rounded_rectangle((lx, ly, lx + lw, ly + lh), radius=max(6, pad // 2),
                           outline=(*primary, 120), width=2)
    lecture_lines = board["lecture_lines"] or [brief.title]
    slot_height = max(1, lh // max(1, len(lecture_lines)))
    lecture_slots = [
        {"x": lx + pad // 2, "y": ly + index * slot_height + pad // 3,
         "width": max(1, lw - pad), "height": max(1, slot_height - pad // 2)}
        for index in range(len(lecture_lines))
    ]
    lecture_text = [f"{index + 1}. {line}" for index, line in enumerate(lecture_lines)]
    lecture_size = _common_fitted_text_size(
        draw, lecture_text, lecture_slots, style, size=board["font"]["body"]
    )
    for text, slot in zip(lecture_text, lecture_slots):
        draw_fitted_text(draw, text, slot, style,
                         size=lecture_size, color=palette["text"])

    main_box = regions["main"]
    mx, my, mw, mh = _box_xywh(main_box)
    draw.rounded_rectangle((mx, my, mx + mw, my + mh), radius=max(8, pad // 2),
                           outline=(*primary, 150), width=3)
    if include_result:
        result_box = regions["result"]
        rx, ry, rw, rh = _box_xywh(result_box)
        draw.rounded_rectangle((rx, ry, rx + rw, ry + rh), radius=max(6, pad // 2),
                               fill=(*_hex_rgb(palette["background"]),),
                               outline=(*secondary, 170), width=2)
        takeaway = board["takeaway"] or ""
        if takeaway:
            text_w = max(1, rw - pad)
            # The character is pasted over this strip, so give the text the room
            # that is left of it rather than letting the last words disappear.
            placed = _character_art(style, canvas.size, brief.id) if include_character else None
            if placed is not None:
                _, char_left, char_top = placed
                if char_top < ry + rh and char_left < rx + rw:
                    text_w = max(1, min(text_w, char_left - (rx + pad // 2) - pad // 2))
            draw_fitted_text(draw, takeaway, {"x": rx + pad // 2, "y": ry + pad // 2,
                                              "width": text_w, "height": max(1, rh - pad)},
                             style, size=board["font"]["body"], color=palette["text"], bold=True)

    # Stable frame accents match the motion renderers and make safe bounds clear.
    draw.line((pad, height - pad, pad + max(24, pad * 3), height - pad), fill=secondary, width=4)
    draw.line((width - pad - max(24, pad * 3), pad, width - pad, pad), fill=primary, width=4)
    if include_character:
        _paste_character(canvas, style, brief.id)
    return canvas


def _character_art(style: StyleConfig, size: tuple[int, int], scene_id: str):
    """The character sheet, sized and positioned for the lower-right corner box.

    Returns ``(image, left, top)`` or ``None``. Callers that draw text near that
    corner use the same geometry to stay clear of it — the character is pasted
    last, so anything it covers is simply lost.
    """
    source = character_asset_path(scene_id)
    if not source.is_file():
        return None
    width, height = size
    box_w, box_h = round(width / 3), round(height / 3)
    with Image.open(source) as raw:
        character = raw.convert("RGBA")
        scale = min(box_w / character.width, box_h / character.height)
        fitted = character.resize(
            (max(1, round(character.width * scale)), max(1, round(character.height * scale))),
            Image.Resampling.LANCZOS,
        )
    pad = style.layout.padding_px
    return fitted, width - pad - fitted.width, height - pad - fitted.height


def _paste_character(canvas: Image.Image, style: StyleConfig, scene_id: str) -> None:
    """Float one homepage character inside the enlarged lower-right corner box."""
    placed = _character_art(style, canvas.size, scene_id)
    if placed is None:
        return
    fitted, left, top = placed
    canvas.paste(fitted, (left, top), fitted)


def _paste_contained(canvas: Image.Image, source: Path, box, style: StyleConfig) -> None:
    """Paste an art asset into a region with aspect-contain semantics."""
    x, y, width, height = _box_xywh(box)
    if width <= 0 or height <= 0:
        return
    with Image.open(source) as src:
        asset = src.convert("RGB")
        scale = min(width / asset.width, height / asset.height)
        fitted = asset.resize((max(1, round(asset.width * scale)), max(1, round(asset.height * scale))),
                              Image.Resampling.LANCZOS)
    # Never crop the generated concept: center it on the board background.
    left = x + (width - fitted.width) // 2
    top = y + (height - fitted.height) // 2
    canvas.paste(fitted, (left, top))


def compose_final(
    source: Path,
    out: Path,
    style: StyleConfig,
    *,
    title: str = "",
    caption: str = "",
    brief: SceneBrief | None = None,
    snap_art: bool = True,
) -> Path:
    """Compose a shared board when a brief is supplied; retain raw compatibility otherwise."""
    if brief is not None:
        canvas = draw_teaching_board(style, brief)
        board = teaching_board(style, brief)
        # Snap only the generated art. Quantizing after local text is drawn would
        # subtly alter exact text colours and damage the typography contract.
        with Image.open(source) as src:
            asset = (snap_to_board(src.convert("RGB"), style) if snap_art
                     else blend_ground(src.convert("RGB"), style))
            temporary = out.with_name(out.stem + "_asset_tmp.png")
            asset.save(temporary, format="PNG")
        try:
            _paste_contained(canvas, temporary, board["regions"]["main"], style)
        finally:
            temporary.unlink(missing_ok=True)
        # Re-draw the board text on top of the art in case an input asset touches
        # its inset boundary; main is isolated from lecture/result by the schema.
        overlay = draw_teaching_board(style, brief)
        # Preserve the generated art while restoring deterministic text/chrome:
        # only copy pixels outside main, then leave main untouched.
        main = _box_xywh(board["regions"]["main"])
        mask = Image.new("L", canvas.size, 255)
        ImageDraw.Draw(mask).rectangle((main[0], main[1], main[0] + main[2], main[1] + main[3]), fill=0)
        canvas.paste(overlay, (0, 0), mask)
        _paste_character(canvas, style, brief.id)
        out.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(out, format="PNG")
        return out

    """Cover-crop to the board size, then draw title/caption with the style tokens."""
    W, H = style.layout.width, style.layout.height
    pad = style.layout.padding_px
    p = style.palette
    base_px = float(style.typography.base_size.removesuffix("px"))
    font_family = style.typography.font_family

    with Image.open(source) as src:
        img = src.convert("RGB")
        scale = max(W / img.width, H / img.height)
        resized = img.resize((round(img.width * scale), round(img.height * scale)), Image.Resampling.LANCZOS)
        left = (resized.width - W) // 2
        top = (resized.height - H) // 2
        canvas = resized.crop((left, top, left + W, top + H))
    canvas = snap_to_board(canvas, style)
    canvas = ambient_particles(canvas, style)

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    bg = _hex_rgb(p.background)

    if title.strip():
        font = load_font(font_family, round(base_px * style.typography.heading_scale * 2.0), bold=True)
        text = _fit_line(draw, title.strip(), font, W - 2 * pad)
        tw, th = _measure(draw, text, font)
        band_h = max(th + pad, round(H * style.layout.title_ratio))
        draw.rectangle([0, 0, W, band_h], fill=(*bg, 200))
        draw.rectangle([pad, band_h - 6, pad + 120, band_h - 2], fill=_hex_rgb(p.secondary))
        draw.text((pad, max(pad * 0.45, (band_h - th) * 0.38)), text, font=font, fill=_hex_rgb(p.text))

    # A quiet frame and corner accents make stills read as authored scenes and
    # keep them visually consistent with the Remotion/Manim compositions.
    frame_color = (*_hex_rgb(p.primary), 150)
    draw.rounded_rectangle([pad // 2, pad // 2, W - pad // 2, H - pad // 2],
                           radius=max(8, pad // 3), outline=frame_color, width=3)
    accent = _hex_rgb(p.secondary)
    corner = max(36, pad * 2)
    draw.line([(pad, H - pad), (pad + corner, H - pad)], fill=accent, width=5)
    draw.line([(W - pad - corner, pad), (W - pad, pad)], fill=accent, width=5)

    if caption.strip():
        font = load_font(font_family, round(base_px * 1.9))
        lines = _wrap(draw, caption.strip(), font, W - 2 * pad - 2 * 24)
        line_h = _measure(draw, "Ag", font)[1] + 8
        band_h = max(len(lines) * line_h + 40, round(H * (1 - style.layout.content_bottom_ratio)))
        y0 = H - band_h
        draw.rounded_rectangle([pad, y0, W - pad, y0 + band_h], radius=14, fill=(*bg, 215))
        draw.rectangle([pad, y0, pad + 8, y0 + band_h], fill=_hex_rgb(p.primary))
        y = y0 + 20
        for line in lines:
            draw.text((pad + 28, y), line, font=font, fill=_hex_rgb(p.text))
            y += line_h

    final = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
    out.parent.mkdir(parents=True, exist_ok=True)
    final.save(out, format="PNG")
    return out


def _hsl(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    h, l, sat = colorsys.rgb_to_hls(*[c / 255 for c in rgb])
    return h, sat, l


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    channels = []
    for value in rgb:
        c = value / 255
        channels.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _hue_gap(a: float, b: float) -> float:
    d = abs(a - b) % 1.0
    return min(d, 1.0 - d)


def snap_to_board(
    img: Image.Image,
    style: StyleConfig,
    *,
    clusters: int = 24,
    merge_distance: int = 26,
) -> Image.Image:
    """Quantize a flat illustration onto the exact style-board colours.

    The prompt already asks for flat vector art with no gradients, so collapsing
    the image to a handful of clusters is lossless in practice — and it is the
    only way to guarantee the still uses the same hexes as the animation and the
    page around it, since a diffusion model only ever approximates a hex code.
    """
    p = style.palette
    # A diffusion still carries film-grain-ish noise, and median cut happily spends
    # most of its clusters describing that noise instead of the drawing. Smooth
    # first, then merge near-identical clusters, so the ground stays one colour.
    # Plenty of clusters: median cut allocates by area, so a small coloured stroke
    # only gets its own bin when the ground is not allowed to hog every one.
    smoothed = img.convert("RGB").filter(ImageFilter.MedianFilter(size=5))
    quantized = smoothed.quantize(colors=clusters, method=Image.MEDIANCUT, dither=Image.Dither.NONE)
    raw = quantized.getpalette() or []
    # getcolors() yields (count, palette_index) pairs.
    counts = {index: count for count, index in (quantized.getcolors() or [])}
    if not counts or len(raw) < 3:
        return img

    ground, ink, muted = _hex_rgb(p.background), _hex_rgb(p.text), _hex_rgb(p.muted)
    accents = {"primary": _hex_rgb(p.primary), "secondary": _hex_rgb(p.secondary),
               "danger": _hex_rgb(p.danger)}
    ground_lum = _relative_luminance(ground)

    entries = []
    for index in counts:
        rgb = tuple(raw[index * 3: index * 3 + 3])
        if len(rgb) == 3:
            entries.append({"index": index, "rgb": rgb, "count": counts[index]})
    if not entries:
        return img
    entries.sort(key=lambda e: -e["count"])

    # Collapse clusters that describe the same flat area.
    groups: list[dict] = []
    for entry in entries:
        home = next(
            (g for g in groups if max(abs(a - b) for a, b in zip(g["rgb"], entry["rgb"])) <= merge_distance),
            None,
        )
        if home is None:
            groups.append({"rgb": entry["rgb"], "count": entry["count"], "members": [entry["index"]]})
        else:
            home["count"] += entry["count"]
            home["members"].append(entry["index"])
    for group in groups:
        rgb = group["rgb"]
        group["lum"] = _relative_luminance(rgb)
        # HSV saturation, i.e. chroma relative to the brightest channel. Absolute
        # chroma under-reads dark colours (a dark teal stroke spans only ~20 levels)
        # and HLS saturation over-reads near-white ones (a cream ground reads as
        # highly saturated) — this measure separates ink, ground and accents cleanly.
        chroma = max(rgb) - min(rgb)
        group["chroma"] = chroma / max(max(rgb), 1)
        group["chroma_abs"] = chroma
        group["hue"] = colorsys.rgb_to_hls(*[c / 255 for c in rgb])[0]
    groups.sort(key=lambda g: -g["count"])

    # The ground is the largest group on the board's own side of the lightness range.
    near_ground = [g for g in groups if abs(g["lum"] - ground_lum) < 0.35]
    ground_group = max(near_ground or groups, key=lambda g: g["count"])

    taken: set[str] = set()
    mapping: dict[int, tuple[int, int, int]] = {}
    for group in groups:
        if group is ground_group:
            target = ground
        elif group["chroma"] < 0.18 or group["chroma_abs"] < 8:
            far_from_ground = abs(group["lum"] - ground_lum) > 0.45
            target = ink if far_from_ground else muted
            if target is muted and "muted" in taken:
                target = ink
            taken.add("ink" if target is ink else "muted")
        else:
            ranked = sorted(accents, key=lambda name: _hue_gap(group["hue"], _hsl(accents[name])[0]))
            choice = next((name for name in ranked if name not in taken), ranked[0])
            target = accents[choice]
            taken.add(choice)
        for index in group["members"]:
            mapping[index] = target

    lut: list[int] = []
    for index in range(256):
        lut.extend(mapping.get(index, ground))
    snapped = quantized.copy()
    snapped.putpalette(lut)
    return snapped.convert("RGB")


def ambient_particles(img: Image.Image, style: StyleConfig, *, count: int = 46, seed: int = 20260904) -> Image.Image:
    """The still's share of the ambient texture that Manim and Remotion carry."""
    rng = random.Random(seed)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    palette = (_hex_rgb(style.palette.primary), _hex_rgb(style.palette.secondary))
    for _ in range(count):
        x = rng.uniform(0, img.width)
        y = rng.uniform(0, img.height)
        r = rng.uniform(img.width * 0.0015, img.width * 0.0038)
        colour = palette[0] if rng.random() > 0.28 else palette[1]
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(*colour, int(255 * rng.uniform(0.05, 0.15))))
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def _hex_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def _measure(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def _fit_line(draw, text: str, font, max_w: int) -> str:
    if _measure(draw, text, font)[0] <= max_w:
        return text
    while text and _measure(draw, text + "…", font)[0] > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if _measure(draw, trial, font)[0] <= max_w or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:3]
