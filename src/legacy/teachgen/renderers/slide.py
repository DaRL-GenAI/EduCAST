"""`slide` renderer — a polished slide rasterized directly to PNG via PIL.

We reuse make_slide.py's text parsing (Title / bullets / Diagram markers) and its
navy+moss+cream palette, but draw straight to a 1920x1080 image with Pillow instead
of going pptx -> LibreOffice -> poppler. That removes two heavy system dependencies
and makes the slide path fast, deterministic, and portable.

(teachgen/make_slide.py still exists for users who want an editable .pptx artifact;
this renderer just doesn't need it for video frames.)

Static output: kind="image"; the compositor stretches it to the narration duration.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..schema import Modality, Segment, VisualAsset
from .base import RenderContext
from .. import make_slide  # the standalone helper, now a teachgen module

# Palette (mirrors make_slide.py) as plain RGB tuples.
NAVY = (0x1B, 0x3A, 0x6B)
MOSS = (0x7A, 0x9A, 0x6B)
PAPER = (0xF7, 0xF6, 0xF0)
INK = (0x2A, 0x2A, 0x2A)
ACCENT = (0x2D, 0x6C, 0xDF)
ACCENT_BG = (0xEA, 0xF0, 0xFB)
WHITE = (0xFF, 0xFF, 0xFF)

W, H = 1920, 1080

SYSTEM = """\
You turn a visual brief into the text of ONE teaching slide, using this exact format:

Title: <a short slide headline>
- <bullet point, <= 12 words>
- <bullet point>
- <up to 5 bullets total>
Diagram: <A> | <B> | <C>

Rules:
- The Title line is required. 2-5 bullets. Use **bold** to lead a key term.
- Include the Diagram line ONLY if a 3-stage "A + B = C" relationship genuinely fits;
  otherwise omit it entirely. Output only the slide text, no preamble, no code fences.
"""


class SlideRenderer:
    modality = Modality.SLIDE

    def render(self, seg: Segment, ctx: RenderContext) -> VisualAsset:
        slide_text = ctx.provider.chat(
            f"Visual brief: {seg.visual_brief}\n\nNarration (for context): {seg.narration}",
            system=SYSTEM,
            max_tokens=600,
        )
        title, bullets, diagram = make_slide.parse_input(slide_text)

        png_path = ctx.out_dir / f"{seg.id}.png"
        _draw_slide(title, bullets, diagram, make_slide.split_bold, png_path)
        return VisualAsset(segment_id=seg.id, kind="image", path=str(png_path))


# --------------------------------------------------------------------- drawing
def _draw_slide(title, bullets, diagram, split_bold, out_path: Path) -> None:
    title = title.replace("**", "")  # title isn't bold-parsed; drop any stray markers
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)

    # double rounded border (navy outer, moss inner)
    d.rounded_rectangle([34, 34, W - 34, H - 34], radius=28, outline=NAVY, width=7)
    d.rounded_rectangle([60, 60, W - 60, H - 60], radius=22, outline=MOSS, width=3)

    title_font = _font(64, bold=True)
    bullet_font = _font(40)
    bullet_bold = _font(40, bold=True)

    # title (wrapped)
    margin = 140
    y = 110
    for line in _wrap(title, title_font, W - 2 * margin, d):
        d.text((margin, y), line, font=title_font, fill=NAVY)
        y += int(title_font.size * 1.2)

    # moss underline under the title
    y += 10
    d.line([(margin, y), (margin + 520, y)], fill=MOSS, width=5)
    d.ellipse([margin - 24, y - 9, margin - 6, y + 9], fill=MOSS)
    y += 60

    # bullets
    has_diagram = bool(diagram)
    bullets_bottom = (H - 360) if has_diagram else (H - 120)
    line_h = int(bullet_font.size * 1.55)
    for b in bullets:
        if y > bullets_bottom:
            break
        d.ellipse([margin, y + 14, margin + 18, y + 32], fill=NAVY)
        _draw_runs(d, margin + 44, y, b, split_bold, bullet_font, bullet_bold,
                   W - margin - 44, line_h)
        # advance by however many wrapped lines the bullet took
        n_lines = max(1, len(_wrap(_plain(b), bullet_font, W - margin - 44, d)))
        y += line_h * n_lines + 16

    if has_diagram:
        _draw_diagram(d, diagram)

    img.save(out_path, format="PNG")


def _draw_runs(d, x, y, text, split_bold, font, bold_font, max_w, line_h):
    """Draw a bullet, honoring **bold** lead-ins, with naive wrapping."""
    cur_x, cur_y = x, y
    for chunk, is_bold in split_bold(text):
        f = bold_font if is_bold else font
        col = NAVY if is_bold else INK
        chunk = chunk.replace("**", "")  # drop any unpaired bold markers left over
        for word in chunk.split(" "):
            if not word:
                continue
            w = d.textlength(word + " ", font=f)
            if cur_x + w > x + max_w:
                cur_x = x
                cur_y += line_h
            d.text((cur_x, cur_y), word + " ", font=f, fill=col)
            cur_x += w


def _draw_diagram(d, nodes):
    labels = (list(nodes) + ["Input", "Process", "Output"])[:3]
    cy = H - 300
    r = 95
    # node A (navy)
    ax = 320
    d.ellipse([ax - r, cy - r, ax + r, cy + r], fill=WHITE, outline=NAVY, width=6)
    _centered(d, _initials(labels[0]), _font(70, bold=True), ax, cy, NAVY)
    _centered(d, labels[0], _font(34, bold=True), ax, cy + r + 40, NAVY)
    # plus
    _centered(d, "+", _font(70, bold=True), ax + 230, cy, MOSS)
    # node B (moss)
    bx = ax + 460
    d.ellipse([bx - r, cy - r, bx + r, cy + r], fill=WHITE, outline=MOSS, width=6)
    _centered(d, _initials(labels[1]), _font(70, bold=True), bx, cy, MOSS)
    _centered(d, labels[1], _font(34, bold=True), bx, cy + r + 40, MOSS)
    # arrow
    ax2 = bx + 200
    d.line([(ax2, cy), (ax2 + 130, cy)], fill=NAVY, width=8)
    d.polygon([(ax2 + 130, cy - 18), (ax2 + 175, cy), (ax2 + 130, cy + 18)], fill=NAVY)
    # result box (accent)
    rx0 = ax2 + 210
    d.rounded_rectangle([rx0, cy - 95, rx0 + 560, cy + 95], radius=18,
                        fill=ACCENT_BG, outline=ACCENT, width=5)
    _centered(d, labels[2], _font(48, bold=True), rx0 + 280, cy, ACCENT)


# ----------------------------------------------------------------------- utils
def _centered(d, text, font, cx, cy, color):
    w = d.textlength(text, font=font)
    asc, desc = font.getmetrics()
    d.text((cx - w / 2, cy - (asc + desc) / 2), text, font=font, fill=color)


def _wrap(text, font, max_w, d):
    words, lines, cur = text.split(" "), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if d.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [text]


def _plain(text: str) -> str:
    return text.replace("**", "")


def _initials(label: str) -> str:
    label = label.strip()
    if not label:
        return "?"
    if any("一" <= c <= "鿿" for c in label):
        return label[:2]
    return label[0].upper()


_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
_BOLD_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _font(size: int, *, bold: bool = False):
    for path in (_BOLD_CANDIDATES if bold else []) + _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()
