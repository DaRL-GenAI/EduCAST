"""Manim tool adapter.

The Executor only generates the construct(self) body. This adapter injects a
theme header from style_config, wraps the body in a guarded Scene class, runs
Manim in a restricted subprocess and parses the deterministic layout guard
report (text out of frame / text overlap) that the guarded scene writes after
every `play()` / `wait()`.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

from pydantic import BaseModel, Field

from ...presentation import character_asset_path
from ...providers.base import Provider
from ...schema import GuardFinding, GuardReport, SceneBrief, StyleConfig, layout_contract, scene_layout_text

CODE_SYSTEM = """\
You write Manim Community Edition v0.19 construct() bodies for teaching animations.

MANDATORY TEACHING LAYOUT (adapted from Code2Video's TeachingScene):
- Start with self.setup_layout(title, [three short lecture lines], kicker="...").
  It draws the fixed title, numbered lecture column and a clean animation stage.
- The right animation stage has a 6x6 grid, A1-F6 (rows top to bottom).
  self.place_at_grid(mob, "B2") fits a point or one-word label into one cell.
  self.place_in_area(mob, "A1", "D6") fits a COMPLETE diagram and its labels
  into that rectangle, respecting both its width and its height.
- Reserve A1-D6 for the main diagram, E1-F6 for the current equation or result.
  Alternatively split A1-D3 and A4-D6 into two comparisons. Never allocate two
  visible independent objects to the same cells.
- Build diagrams in local coordinates, group ALL geometry, arrows, measurements
  and attached labels, then place the complete group once. Add no unplaced text.
- self.show_step(index, *mobs) highlights a zero-based lecture line and reveals
  its animation; call it directly, not inside self.play(). Lecture lines and the
  title remain at fixed size/position; only their colors change.
- Show each object once: use show_step(index, objects) OR show_step(index)
  followed by reveal(objects). Calling FadeIn/reveal on an already visible
  object restarts its entrance and makes it blink. Animate its properties to
  update it; keep diagram geometry visible throughout value changes.
- Each of the three lecture lines needs a visible explanatory action: vary a
  value, move a force, compare two states, grow a graph, or transform an equation.
  FadeIn alone is not a teaching animation. Use 4-6 beats with a visible worked
  numerical example and a final result tied to the brief.
- Replace old results with self.swap(old, new); do not stack successive formulas.
- Never pre-hide mobjects with set_opacity(0) before FadeIn/self.reveal. Keep
  objects off-scene until needed. Do not animate a group and its child in the
  same self.play call. Rotating a diagram must include all attached labels.
- Write # === Lecture Line 1 === etc. before the corresponding animation block.

Available globals (already defined, do not redefine): BACKGROUND_COLOR, PRIMARY_COLOR,
SECONDARY_COLOR, TEXT_COLOR, MUTED_COLOR, DANGER_COLOR, TEXT_FONT, SAFE_PAD,
BASE_FONT_SIZE, HEADING_SCALE, SAFE_W, SAFE_H (usable width/height in Manim units),
plus helpers:
  heading(text)            -> Text placed at the top inside the safe margin
  caption(text)            -> Text placed at the bottom inside the safe margin
  fit_width(mob, max_w)    -> scales mob down if wider than max_w (default SAFE_W)
  clamp_inside(mob)        -> shifts mob back inside the safe frame

USE THE SCENE KIT — do not hand-roll what it already composes. Every helper keeps
itself inside the safe frame and carries the lesson's visual language:
  title_bar(text, kicker="")     top band: kicker + bold title + accent rule
  label(text, size=1.0, color)   body text at the board's scale
  eyebrow(text)                  small uppercase micro-label
  card(content, label_text="")   bordered panel with a soft tinted fill
  chip(value, unit, name)        KPI tile: big number + unit + quiet name
  callout(text)                  soft block with a thick rule on the leading edge
  self.annotate(mob, text, RIGHT, obstacles=(diagram,))
                                nearby label + leader that follow the target
  row(*mobs) / column(*mobs)     arranged groups, auto-fitted to the safe frame
  place(mob)                     centre a group in the content band under the title
  bar_chart(values, labels)      small comparison chart with value labels
  self.reveal(*mobs)             staggered entrance (richer than one FadeIn)
  self.emphasize(mob)            pulse the thing the narration is naming
  self.swap(old, new)            replace a step in place, keeping the frame clean

These three PLAY immediately — call them on their own line, never inside
self.play(...). Pass the mobjects themselves: there is no .get_parent() and no
.parent in Manim, and swap() needs only the old and the new mobject.

COMPOSE A FULL FRAME using the fixed lecture column and the grid stage. Use a
large, readable diagram and a dedicated bottom formula/result region. Fill the
stage with useful geometry, measurement guides, color-linked variables and a
concrete comparison. Use run_time and self.wait() to fill TARGET SECONDS.

LAYOUT RULES (violations are detected automatically and fail the scene):
- Use the fixed teaching-board composition: title_bar at the top, a content band
  below it, and optional caption/chrome at the bottom. Treat the content band as
  a 6×6 anchor grid (columns A-F, rows 1-6): place independent objects in
  different cells or non-overlapping 2×2 areas, then call place(group) once.
- EVERY independent object or group reaches the stage through place_at_grid(obj,
  'B2'), place_in_area(obj, 'A1', 'C3') or place(group) — never .to_edge(),
  .move_to(coordinates) or hand-computed positions.
- THE STAGE NEEDS A DRAWING. Build the scene's non-text visual (circuit, axes,
  geometry, chart) and give it the block of rows it needs, typically
  place_in_area(diagram, 'A1', 'D6') or the rows above the text stack. A stage made
  only of text rows is a slide: the lecture column already carries the words.
- LOOSE TEXT IS A ROW STACK. A caption, formula or chip row that is NOT part of the
  drawing takes one FULL-WIDTH row band of the rows the drawing leaves —
  place_in_area(obj, 'E1', 'E6'), then 'F1','F6' — in reading order, one item per
  row band. Never park a formula beside the drawing at an arbitrary height and
  never put two text items in the same row band. Labels that belong to the drawing
  stay attached to their part (annotate/next_to within one grid unit). Those three calls are the only
  vocabulary a layout fix can be expressed in, so a scene that positions by hand
  can only be repaired by rewriting it whole.
- One annotation cluster per region. Two brace+label groups (or two of anything
  that carries its own labels) must never occupy the same anchors: give them
  different areas, or show one, FadeOut its braces and labels, then show the next
  in the same place.
- Prefer row()/column()/card()/callout()/annotate() and the grid-safe place()
  helpers over raw coordinates. Never stack two labels at the same point.
- Every text/formula must stay inside the safe frame. Long text: split into lines
  or call fit_width().
- Two text objects must never overlap. Use .next_to(other, DOWN, buff=0.35) or
  VGroup(...).arrange(DOWN, buff=0.4); never .move_to() two labels near the same spot.
- A label must not sit on top of the diagram either. Place every label with
  .next_to(shape, UP/DOWN/LEFT/RIGHT, buff=0.3) so it lands in clear space, never
  inside a filled polygon, across a brace, or on a beam. Dimension braces go
  BELOW the object they measure, offset from its edge, not on its centre line.
- If you rotate part of a diagram, rotate its labels with it or place them after
  the rotation. Labels positioned with .next_to() before a rotate() stay behind
  and end up crossing the shape they belonged to.
- Before showing a new equation/step in the same region, FadeOut or
  ReplacementTransform the previous one. Use short diagram labels; the fixed
  lecture column carries the explanatory sentences.
- Diagram on the grid; title and lecture column managed by setup_layout.
- For diagram annotations use self.annotate(target, 'short label', RIGHT,
  obstacles=(complete_diagram,)) AFTER placing the complete diagram. Pass future
  comparison shapes as obstacles too. The helper tries nearby free sides without
  shrinking the text. If no side fits, reserve a compact label lane beside the
  diagram or shorten the label. Never move its text separately from its leader.
- Keep one annotation per target/state; combine a name and value in one short
  multiline label. FadeOut the old annotation before changing states, then build
  one for the new target. Never copy an annotation to label a different target.
- Plan axes ranges and curve domains for ALL states before placing the complete
  diagram. Adding larger curves after placement can draw through the title.
- Fonts: Text(..., font=TEXT_FONT, font_size=BASE_FONT_SIZE*1.6) for labels, *2.2 for
  headings. Colors only from the palette globals.
- Build with the kit first; drop to raw Line/Arrow/Polygon/Circle/Brace/Axes only
  for the actual diagram geometry the kit does not cover.
  No external images, no 3D, no Sound, no network, no imports, no file access.
- Pace the animation to the TARGET SECONDS using run_time= and self.wait(); end with
  self.wait(1).
- FOLLOW THE ANIMATION PLAN. The body is one section per lecture line, in order:
  open section N with self.show_step(N-1, ...) so the line lights up as its visual
  arrives, then play that line's planned step. (Comments are stripped before
  rendering, so the structure has to be in the calls, not in a header comment.)
- Most steps must change the DIAGRAM, not just the text: Transform /
  ReplacementTransform of a shape, MoveAlongPath or .animate.shift/.scale/
  .set_color on an object already on screen, Create/Uncreate of new geometry, a
  number updating. self.emphasize() is punctuation between steps — a section whose
  only motion is a pulse, or swapping one line of text for another, is a slide with
  extra frames, and the plan exists because that teaches nothing the lecture column
  has not already said.
- Colour-link each block to its line: the objects a block introduces use
  PRIMARY_COLOR or SECONDARY_COLOR consistently, so the eye can pair the lit
  lecture line with the thing that just changed.
- Output ONLY the Python statements that go INSIDE construct(self) — no class,
  no imports, no markdown fences.
"""

FORBIDDEN_NAMES = {
    "open", "exec", "eval", "compile", "__import__", "input", "breakpoint",
    "os", "sys", "subprocess", "socket", "pathlib", "requests", "urllib",
    "globals", "locals", "vars", "getattr", "setattr", "delattr",
}
FORBIDDEN_ATTRIBUTES = {
    "system", "popen", "spawn", "unlink", "remove", "rmdir", "rmtree",
    "write_text", "write_bytes", "read_text", "read_bytes", "urlopen",
}
TEXT_TYPES = "(Text, MarkupText, Paragraph, Tex, MathTex, SingleStringMathTex)"
# Retained for old run configuration; the default board is a clean drawing stage.
AMBIENT_PARTICLES = int(os.environ.get("EDUHARNESS_AMBIENT_PARTICLES", "0"))


def resolve_manim_font(requested: str) -> str:
    """Return an installed family so Manim never silently changes typography.

    Browser CSS can download Inter, while Manim relies on Fontconfig.  If Inter
    is absent, Manim silently falls back to a different family and changes text
    widths/wrapping. Resolve once when assembling the script and use the same
    explicit fallback on every renderer host.
    """
    requested = str(requested or "").strip() or "DejaVu Sans"
    if bundled_manim_fonts(requested):
        return "Inter"
    try:
        match = subprocess.run(
            ["fc-match", "-f", "%{family}", requested],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        if match:
            return match.split(",", 1)[0].strip()
    except Exception:
        pass
    return "DejaVu Sans"


def bundled_manim_fonts(family: str) -> list[Path]:
    if family.casefold() != "inter":
        return []
    folder = Path(__file__).resolve().parents[2] / "assets/fonts/inter"
    return sorted(folder.glob("*.ttf"))


def manim_font_cache_key(family: str) -> str:
    """Invalidate text SVGs when a font is installed, replaced or removed."""
    digest = hashlib.sha256(b"eduharness-pango-shape96-v1")
    digest.update(family.encode())
    paths = bundled_manim_fonts(family)
    if not paths:
        for pattern in (family, family + ":bold"):
            try:
                match = subprocess.run(["fc-match", "-f", "%{file}", pattern],
                                       capture_output=True, text=True, timeout=5)
                path = Path(match.stdout.strip())
                if path.is_file():
                    paths.append(path)
            except (OSError, subprocess.SubprocessError):
                pass
    for path in paths:
        digest.update(str(path).encode())
        digest.update(path.read_bytes())
    if not paths:
        digest.update(b"unresolved")
    return digest.hexdigest()[:20]

# Fallback construct when the LLM fails entirely. Deliberately generic so the
# reviewer fails it for "unrelated to the brief" instead of shipping it.
FALLBACK_BODY = textwrap.dedent(
    """\
    self.setup_layout("Teaching Scene", [
        "State the idea",
        "Connect it to the example",
        "Keep the result visible",
    ], kicker="RENDER FALLBACK")
    dot = Dot(color=PRIMARY_COLOR).scale(2)
    self.place_at_grid(dot, "C3")
    self.reveal(dot)
    self.emphasize(dot)
    self.wait(1)
    """
)


class _ManimBody(BaseModel):
    construct_body: str = Field(..., description="Python statements for construct(self)")
    scene_class_name: str = Field("EduScene", description="Valid Python class name")
    fallback_reason: str = Field("", exclude=True)


THEME_HEADER = '''\
import json as _json
import random as _random
import textwrap as _textwrap
import weakref as _weakref
import manimpango as _manimpango
from manim import *

for _font_file in {font_files}:
    if not _manimpango.register_font(_font_file):
        raise RuntimeError("Could not load planner font: " + _font_file)

# Text is shaped by Pango before Manim scales the vector.  Very small source
# sizes quantize glyph advances and create the loose/uneven tracking visible in
# the old lecture column. Code2Video shapes at a larger size and scales the
# finished vectors; keep that behavior in one wrapper for every renderer helper
# and generated Text call.
_ManimText = Text
_TEXT_SHAPE_SIZE = 96.0
_TEXT_CACHE_NAMESPACE = "eduharness-text-{font_cache_key}"
config.text_dir = "{{media_dir}}/texts/" + _TEXT_CACHE_NAMESPACE

class Text(_ManimText):
    def __init__(self, text, fill_opacity=1.0, stroke_width=0, color=None,
                 font_size=48, **kwargs):
        requested = float(font_size)
        shape_size = max(requested, _TEXT_SHAPE_SIZE)
        explicit_dimensions = kwargs.get("height") is not None or kwargs.get("width") is not None
        super().__init__(text, fill_opacity=fill_opacity, stroke_width=stroke_width,
                         color=color, font_size=shape_size, **kwargs)
        if not explicit_dimensions:
            self.scale(requested / shape_size)

BACKGROUND_COLOR = "{bg}"
PRIMARY_COLOR = "{primary}"
SECONDARY_COLOR = "{secondary}"
TEXT_COLOR = "{text}"
MUTED_COLOR = "{muted}"
DANGER_COLOR = "{danger}"
TEXT_FONT = "{font}"
SAFE_PAD = {pad}
BASE_FONT_SIZE = {base_size}
HEADING_SCALE = {heading_scale}
LAYOUT_TITLE_RATIO = {title_ratio}
LAYOUT_CONTENT_TOP_RATIO = {content_top_ratio}
LAYOUT_CONTENT_BOTTOM_RATIO = {content_bottom_ratio}
LAYOUT_TEXT_RATIO = {text_ratio}
LAYOUT_VISUAL_RATIO = {visual_ratio}
LAYOUT_GAP_RATIO = {content_gap_ratio}
AMBIENT_PARTICLES = {particles}
SCENE_LABEL = "{scene_label}"
SCENE_INDEX = {scene_index}
SCENE_TOTAL = {scene_total}
CHARACTER_PATH = r"{character_path}"

config.background_color = BACKGROUND_COLOR
config.pixel_width = {w}
config.pixel_height = {h}
config.frame_rate = 30
config.frame_width = 14.222222
config.frame_height = 8.0

_PAD_X = SAFE_PAD / config.pixel_width * config.frame_width
_PAD_Y = SAFE_PAD / config.pixel_height * config.frame_height
SAFE_W = config.frame_width - 2 * _PAD_X
SAFE_H = config.frame_height - 2 * _PAD_Y
_TEXT_TYPES = (_ManimText, MarkupText, Paragraph, Tex, MathTex, SingleStringMathTex)


def fit_width(mob, max_w=None):
    max_w = SAFE_W if max_w is None else max_w
    if mob.width > max_w:
        mob.scale_to_fit_width(max_w)
    return mob


def _decor(mob):
    """Mark a shape as scenery the guard should let text sit on.

    A card's panel, a callout's ground and a leader line are *drawn behind or
    into* a label on purpose. Everything the model draws itself stays unmarked,
    so a brace struck through a caption still reads as a collision.
    """
    mob._edu_decor = True
    return mob


def clamp_inside(mob):
    fx, fy = config.frame_width / 2 - _PAD_X, config.frame_height / 2 - _PAD_Y
    if mob.get_right()[0] > fx:
        mob.shift(LEFT * (mob.get_right()[0] - fx))
    if mob.get_left()[0] < -fx:
        mob.shift(RIGHT * (-fx - mob.get_left()[0]))
    if mob.get_top()[1] > fy:
        mob.shift(DOWN * (mob.get_top()[1] - fy))
    if mob.get_bottom()[1] < -fy:
        mob.shift(UP * (-fy - mob.get_bottom()[1]))
    return mob


def heading(text, color=None, font_size=None):
    t = Text(text, font=TEXT_FONT, color=color or TEXT_COLOR,
             font_size=font_size or BASE_FONT_SIZE * HEADING_SCALE * 1.8)
    fit_width(t)
    t.to_edge(UP, buff=_PAD_Y)
    return t


def caption(text, color=None, font_size=None):
    t = Text(text, font=TEXT_FONT, color=color or MUTED_COLOR,
             font_size=font_size or BASE_FONT_SIZE * 1.4)
    fit_width(t)
    t.to_edge(DOWN, buff=_PAD_Y)
    return t


# --------------------------------------------------------------- scene kit
# Composed, guard-safe primitives. The model calls these instead of hand-rolling
# shapes: they keep themselves inside the safe frame, they never stack text on
# text, and they carry the same visual language as the slides and the web page.

def _fit(mob, max_w=None, max_h=None):
    if max_w and mob.width > max_w:
        mob.scale_to_fit_width(max_w)
    if max_h and mob.height > max_h:
        mob.scale_to_fit_height(max_h)
    return mob


def label(text, size=1.0, color=None, weight=NORMAL):
    return Text(str(text), font=TEXT_FONT, color=color or TEXT_COLOR, weight=weight,
                font_size=BASE_FONT_SIZE * 1.35 * size)


def _wrap_lecture(text, max_width):
    """Break at words using shaped glyph widths, rather than 23 characters."""
    rows = []
    def width(value):
        return label(value, size=0.69, color=MUTED_COLOR).width
    for paragraph in str(text).splitlines():
        current = ""
        for word in paragraph.split():
            trial = (current + " " + word).strip()
            if width(trial) <= max_width:
                current = trial
                continue
            if current:
                rows.append(current)
            current = ""
            # Long unbroken identifiers and CJK text may need glyph breaks.
            for character in word:
                trial = current + character
                if current and width(trial) > max_width:
                    rows.append(current)
                    current = character
                else:
                    current = trial
        if current:
            rows.append(current)
    return "\\n".join(rows)


def eyebrow(text, color=None):
    """Small uppercase micro-label, the one the page uses above every heading."""
    t = Text(str(text).upper(), font=TEXT_FONT, color=color or MUTED_COLOR,
             font_size=BASE_FONT_SIZE * 0.85)
    return t


def title_bar(text, kicker=""):
    """Top band: kicker, title, and the secondary rule under it."""
    title = Text(str(text), font=TEXT_FONT, color=TEXT_COLOR, weight=BOLD,
                 font_size=BASE_FONT_SIZE * HEADING_SCALE * 1.7)
    fit_width(title)
    rule = Line(ORIGIN, RIGHT * 1.1, color=SECONDARY_COLOR, stroke_width=6)
    parts = VGroup()
    if kicker:
        parts.add(eyebrow(kicker))
    parts.add(title, rule)
    parts.arrange(DOWN, aligned_edge=LEFT, buff=0.16)
    parts.to_corner(UL, buff=_PAD_Y)
    return parts


def card(content, label_text="", accent=None, pad=0.34):
    """Bordered panel with a soft fill — the page's card, in Manim."""
    accent = accent or PRIMARY_COLOR
    body = VGroup(content)
    if label_text:
        tag = eyebrow(label_text, accent)
        body = VGroup(tag, content).arrange(DOWN, aligned_edge=LEFT, buff=0.22)
    box = RoundedRectangle(
        corner_radius=0.16, width=body.width + pad * 2, height=body.height + pad * 2,
        stroke_color=accent, stroke_width=2.5,
        fill_color=accent, fill_opacity=0.07,
    )
    box.move_to(body)
    return VGroup(_decor(box), body)


def chip(value, unit="", name="", accent=None):
    """A KPI tile: big number, small unit, quiet name — matches the page's strip."""
    accent = accent or PRIMARY_COLOR
    number = Text(str(value), font=TEXT_FONT, color=accent, weight=BOLD,
                  font_size=BASE_FONT_SIZE * 2.4)
    head = VGroup(number)
    if unit:
        head.add(Text(str(unit), font=TEXT_FONT, color=accent, font_size=BASE_FONT_SIZE * 1.1))
        head.arrange(RIGHT, aligned_edge=DOWN, buff=0.12)
    stack = VGroup(head)
    if name:
        stack.add(eyebrow(name))
        stack.arrange(DOWN, aligned_edge=LEFT, buff=0.16)
    return card(stack, accent=accent, pad=0.3)


def callout(text, accent=None):
    """The verdict block: soft ground with a thick rule on the leading edge."""
    accent = accent or SECONDARY_COLOR
    body = label(text, 0.95)
    _fit(body, SAFE_W * 0.62)
    bar = Rectangle(width=0.09, height=body.height + 0.42,
                    fill_color=accent, fill_opacity=1, stroke_width=0)
    ground = Rectangle(width=body.width + 0.7, height=body.height + 0.42,
                       fill_color=accent, fill_opacity=0.08, stroke_width=0)
    group = VGroup(_decor(ground), _decor(bar), body)
    ground.move_to(body)
    bar.next_to(ground, LEFT, buff=0).align_to(ground, LEFT)
    return group


def annotate(mob, text, direction=UP, accent=None, buff=0.42):
    """Leader line from a shape to a label, so callouts never float unattached."""
    accent = accent or MUTED_COLOR
    tag = label(text, 0.8, accent)
    tag.next_to(mob, direction, buff=buff)
    clamp_inside(tag)
    leader = Line(mob.get_edge_center(direction), tag.get_edge_center(-direction),
                  color=accent, stroke_width=2)
    leader._edu_label_ref = _weakref.ref(tag)
    return _StaticAnnotation(leader, tag)


class _StaticAnnotation(VGroup):
    def __deepcopy__(self, memo):
        result = super().__deepcopy__(memo)
        result[0]._edu_label_ref = _weakref.ref(result[1])
        return result


def _follow_annotation(group, dt=0):
    target = group._edu_target_ref()
    if target is None:
        return
    leader, tag, anchor = group.submobjects
    leader._edu_label_ref = _weakref.ref(tag)
    delta = target.get_center() - anchor.get_center()
    tag.shift(delta)
    direction = tag.get_center() - target.get_center()
    direction /= max(np.linalg.norm(direction), 1e-6)
    # Keep the edge gap on scale/stretch too. The invisible extent transforms
    # with a complete diagram, so a group animation is not applied twice.
    tag.shift(target.get_edge_center(direction) - anchor.get_edge_center(direction) - delta)
    anchor.stretch_to_fit_width(max(target.width, 1e-5))
    anchor.stretch_to_fit_height(max(target.height, 1e-5))
    anchor.move_to(target)
    start = target.get_edge_center(direction)
    end = tag.get_edge_center(-direction)
    if np.linalg.norm(end - start) > 1e-6:
        leader.put_start_and_end_on(start, end)


class _FollowingAnnotation(_StaticAnnotation):
    def __init__(self, target, tag, direction, accent):
        leader = Line(target.get_edge_center(direction), tag.get_edge_center(-direction),
                      color=accent, stroke_width=1.5)
        leader._edu_label_ref = _weakref.ref(tag)
        anchor = Rectangle(width=max(target.width, 1e-5), height=max(target.height, 1e-5),
                           stroke_width=0, fill_opacity=0).move_to(target)
        super().__init__(leader, tag, anchor)
        # Weak references survive Manim's animation copies without copying the
        # target itself. The invisible anchor also transforms with a diagram
        # group, preventing double movement when both are moved together.
        self._edu_target_ref = _weakref.ref(target)
        self.add_updater(_follow_annotation)

    def __deepcopy__(self, memo):
        result = super().__deepcopy__(memo)
        target = self._edu_target_ref()
        target_copy = memo.get(id(target), target)
        if target_copy is not None:
            result._edu_target_ref = _weakref.ref(target_copy)
        return result


def row(*mobs, buff=0.7, max_w=None):
    group = VGroup(*mobs).arrange(RIGHT, buff=buff)
    return _fit(group, max_w or SAFE_W)


def column(*mobs, buff=0.42, align=LEFT, max_h=None):
    group = VGroup(*mobs).arrange(DOWN, aligned_edge=align, buff=buff)
    return _fit(group, None, max_h or SAFE_H * 0.72)


def content_area():
    """The right animation band — keep complete groups out of the lecture column."""
    stage_left = -config.frame_width / 2 + _PAD_X + SAFE_W * (LAYOUT_TEXT_RATIO + LAYOUT_GAP_RATIO)
    stage_width = SAFE_W * LAYOUT_VISUAL_RATIO
    area = Rectangle(width=stage_width, height=SAFE_H * 0.66, stroke_width=0)
    area.move_to([stage_left + stage_width / 2, -config.frame_height * 0.06, 0])
    return _decor(area)


def place(mob, area=None):
    """Centre a mobject in the content band and keep it inside the safe frame."""
    target = area or content_area()
    _fit(mob, target.width, target.height)
    mob.move_to(target)
    return clamp_inside(mob)


def bar_chart(values, labels=None, accent=None, height=2.6, width=None):
    """Small comparison chart — bars, value labels, baseline."""
    accent = accent or PRIMARY_COLOR
    values = [float(v) for v in values]
    peak = max(values + [1e-6])
    width = width or min(SAFE_W * 0.6, 1.5 * len(values))
    slot = width / max(len(values), 1)
    bars = VGroup()
    for i, value in enumerate(values):
        h = max(0.12, height * value / peak)
        bar = Rectangle(width=slot * 0.52, height=h, stroke_width=0,
                        fill_color=accent if i % 2 == 0 else SECONDARY_COLOR, fill_opacity=0.9)
        bar.move_to(RIGHT * (i * slot) + UP * h / 2)
        stack = VGroup(bar, label(_trim(value), 0.72).next_to(bar, UP, buff=0.14))
        if labels and i < len(labels):
            stack.add(eyebrow(labels[i]).next_to(bar, DOWN, buff=0.18))
        bars.add(stack)
    bars.arrange(RIGHT, buff=slot * 0.42, aligned_edge=DOWN)
    base = Line(bars.get_left(), bars.get_right(), color=MUTED_COLOR, stroke_width=2)
    base.next_to(bars, DOWN, buff=0.0)
    return VGroup(bars, base)


def _trim(value):
    if float(value).is_integer():
        return str(int(value))
    return ("%.2f" % float(value)).rstrip("0").rstrip(".")


def emphasize(scene, mob, color=None, scale=1.08, run_time=0.7):
    """Pulse a mobject so the eye lands where the narration is."""
    scene.play(Indicate(mob, color=color or PRIMARY_COLOR, scale_factor=scale), run_time=run_time)


def reveal(scene, *mobs, lag=0.18, run_time=1.1):
    """Reveal new objects, preserving already displayed members and timing."""
    displayed = {{id(part) for root in scene.mobjects for part in root.get_family()
                 if part.has_points() and scene._visible(part)}}
    pending = []
    claimed = set(displayed)

    def collect(mob):
        parts = [part for part in mob.get_family() if part.has_points()]
        if not parts or all(id(part) in claimed for part in parts):
            return
        if any(id(part) in claimed for part in parts):
            # A new group can contain an already displayed arrow plus a new
            # label. Animate only the new children, never reset the whole group.
            if mob.has_points() and id(mob) not in claimed:
                raise ValueError('Reveal new geometry separately from its visible children')
            for child in mob.submobjects:
                collect(child)
            return
        pending.append(mob)
        claimed.update(id(part) for part in parts)

    # Process outer groups first so parent/child arguments cannot both FadeIn.
    roots = [mob for i, mob in enumerate(mobs)
             if not any(mob is earlier for earlier in mobs[:i])
             and not any(mob is child for other in mobs if other is not mob
                         for child in other.get_family()[1:])]
    for mob in roots:
        collect(mob)
    if not pending:
        scene.wait(run_time)
        return
    for mob in pending:
        # FadeIn restores the starting opacity, so a pre-hidden object would
        # otherwise remain invisible even after the entrance has finished.
        if hasattr(mob, "get_family"):
            parts = [part for part in mob.get_family() if len(getattr(part, "points", []))]
            if parts and all(max(float(part.get_fill_opacity()),
                                 float(part.get_stroke_opacity())) < 0.01 for part in parts):
                mob.set_opacity(1)
    scene.play(LaggedStart(*[FadeIn(m, shift=UP * 0.25) for m in pending],
                           lag_ratio=lag), run_time=run_time)


def swap(scene, old, new, run_time=0.8):
    """Replace one step with the next in the same spot; keeps the frame uncluttered."""
    new.move_to(old)
    scene.play(ReplacementTransform(old, new), run_time=run_time)


def _label_of(mob):
    for attr in ("text", "tex_string", "original_text"):
        value = getattr(mob, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()[:60]
    return type(mob).__name__


class _EduGuardScene(Scene):
    """Scene base that audits text layout after every play()/wait()."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._guard_findings = []
        self._guard_seen = set()
        self._guard_steps = 0
        self._guard_last_sample = -1.0
        self._guard_text_ids = set()
        self._guard_moved = 0

    # These play immediately. They also return a no-op animation so that wrapping
    # them in self.play(*...) — the shape a model reaches for — cannot crash.
    def reveal(self, *mobs, lag=0.18, run_time=1.1):
        """Staggered entrance — richer than showing everything at once."""
        reveal(self, *mobs, lag=lag, run_time=run_time)
        return (Wait(run_time=0.01),)

    def emphasize(self, mob, color=None, scale=1.08, run_time=0.7):
        """Pulse a mobject so the eye lands where the narration is."""
        emphasize(self, mob, color=color, scale=scale, run_time=run_time)
        return (Wait(run_time=0.01),)

    def swap(self, old, new, run_time=0.8):
        """Replace one step with the next in the same spot."""
        swap(self, old, new, run_time=run_time)
        return (Wait(run_time=0.01),)

    def setup(self):
        """Ambient particle field — the same quiet texture the motion graphics use.

        Static and seeded so frames stay deterministic, drawn first so it sits
        behind everything, and made of Dots so the text guard ignores it.
        """
        super().setup()
        try:
            rng = _random.Random(20260904)
            field = VGroup()
            for _ in range(AMBIENT_PARTICLES):
                x = rng.uniform(-config.frame_width / 2, config.frame_width / 2)
                y = rng.uniform(-config.frame_height / 2, config.frame_height / 2)
                dot = Dot(point=[x, y, 0], radius=rng.uniform(0.012, 0.030),
                          color=PRIMARY_COLOR if rng.random() > 0.28 else SECONDARY_COLOR)
                dot.set_opacity(rng.uniform(0.05, 0.15))
                field.add(_decor(dot))
            self.add(_decor(field))
        except Exception:
            pass
        try:
            if SCENE_LABEL:
                tag = Text(SCENE_LABEL, font=TEXT_FONT, color=MUTED_COLOR,
                           font_size=BASE_FONT_SIZE * 0.8)
                # Bottom-left: the character accent owns the bottom-right corner and
                # is a third of the frame tall, so a tag there is read as occluded text.
                tag.to_corner(DL, buff=_PAD_Y * 0.7)
                tag.set_opacity(0.75)
                self.add(tag)
            if SCENE_TOTAL > 1:
                width = config.frame_width - 2 * _PAD_X
                track = Line(LEFT * width / 2, RIGHT * width / 2,
                             color=MUTED_COLOR, stroke_width=3).set_opacity(0.25)
                done = width * SCENE_INDEX / SCENE_TOTAL
                bar = Line(LEFT * width / 2, LEFT * width / 2 + RIGHT * max(done, 0.001),
                           color=PRIMARY_COLOR, stroke_width=3)
                chrome = VGroup(_decor(track), _decor(bar))
                chrome.to_edge(DOWN, buff=_PAD_Y * 0.55)
                self.add(_decor(chrome))
        except Exception:
            pass

    def play(self, *args, **kwargs):
        # Include text added directly before its first animation. FadeIn-created
        # objects are added by Manim later, so entrance ghosts remain excluded.
        self._guard_text_ids.update(id(m) for m in self._texts())
        super().play(*args, **kwargs)
        self._guard_check("play")

    def add(self, *mobjects):
        result = super().add(*mobjects)
        added = {{id(m) for root in mobjects for m in root.get_family()}}
        self._pending_annotations = [ref for ref in getattr(self, '_pending_annotations', [])
                                     if ref() is not None and id(ref()) not in added]
        return result

    def update_to_time(self, t):
        super().update_to_time(t)
        now = float(getattr(self.renderer, "time", 0.0))
        # Check moving, already-visible labels during animation as well as the
        # final poses. Entrance/exit ghosts are excluded until their first pose.
        if now - self._guard_last_sample >= 0.25:
            self._guard_last_sample = now
            self._guard_check("motion", persist=False)

    def wait(self, *args, **kwargs):
        super().wait(*args, **kwargs)
        self._guard_check("wait")

    def _visible(self, mob):
        try:
            opacity = max(float(mob.get_fill_opacity()), float(mob.get_stroke_opacity()))
        except Exception:
            opacity = 1.0
        return opacity > 0.05 and max(mob.width, mob.height) > 0.01

    def _texts(self):
        found = []
        seen = set()

        def visit(m):
            if isinstance(m, _TEXT_TYPES):
                if id(m) not in seen and self._visible(m):
                    seen.add(id(m))
                    found.append(m)
                return
            for sm in m.submobjects:
                visit(sm)

        for m in self.mobjects:
            visit(m)
        return found

    def _occluders(self):
        """Drawn geometry that is neither text nor the kit's own scenery.

        The text-vs-text check below is blind to the collision that actually
        makes a frame look broken: a brace, arrow or filled polygon sitting on
        top of a label. These are the leaves that can do it.
        """
        found = []

        def visit(m):
            if getattr(m, "_edu_decor", False) or isinstance(m, _TEXT_TYPES):
                return
            if isinstance(m, _FollowingAnnotation):
                m[0]._edu_label_ref = _weakref.ref(m[1])
            try:
                drawn = len(m.points) > 1
            except Exception:
                drawn = False
            if drawn and self._visible(m):
                found.append(m)
            # Axes/Arrow own a stroke AND children (ticks/tips). Checking only
            # leaves silently discards their shafts, including the y-axis.
            for sm in m.submobjects:
                visit(sm)

        for m in self.mobjects:
            visit(m)
        return list({{id(m): m for m in found}}.values())

    def _add(self, kind, severity, message, subjects, at):
        key = (kind, tuple(subjects))
        if key in self._guard_seen:
            return
        self._guard_seen.add(key)
        self._guard_findings.append({{
            "kind": kind, "severity": severity, "message": message,
            "subjects": list(subjects), "at_seconds": round(float(at), 3),
        }})

    @staticmethod
    def _segments_cross_box(segments, left, right, bottom, top):
        """Clip sampled stroke segments to a rectangle (including zero-width axes)."""
        if not len(segments):
            return False
        starts, delta = segments[:, 0], segments[:, 1] - segments[:, 0]
        lo = np.zeros(len(segments))
        hi = np.ones(len(segments))
        valid = np.ones(len(segments), dtype=bool)
        for axis, lower, upper in ((0, left, right), (1, bottom, top)):
            parallel = np.abs(delta[:, axis]) < 1e-10
            valid &= ~parallel | ((starts[:, axis] >= lower) & (starts[:, axis] <= upper))
            denom = np.where(parallel, 1, delta[:, axis])
            a = (lower - starts[:, axis]) / denom
            b = (upper - starts[:, axis]) / denom
            lo = np.maximum(lo, np.where(parallel, 0, np.minimum(a, b)))
            hi = np.minimum(hi, np.where(parallel, 1, np.maximum(a, b)))
        return bool(np.any(valid & (lo <= hi)))

    def _shape_crosses_box(self, shape, left, right, bottom, top, clearance=0.015):
        """Test ink, not a curve's bounding rectangle or its Bezier control polygon.

        Subpaths stay separate, so invisible bridges across dashed lines are not
        obstacles. Filled geometry is also tested when it fully contains text.
        Only explicit kit decorations are exempted by _occluders().
        """
        if isinstance(shape, ImageMobject):
            return (min(right, shape.get_right()[0]) > max(left, shape.get_left()[0])
                    and min(top, shape.get_top()[1]) > max(bottom, shape.get_bottom()[1]))
        fill = float(shape.get_fill_opacity()) > 0.05
        stroke = float(shape.get_stroke_opacity()) > 0.05 and float(shape.get_stroke_width()) > 0
        if not fill and not stroke:
            return False
        # Cairo expresses stroke widths in scene units via this coefficient;
        # output resolution changes pixels, not the geometry clearance.
        stroke_unit = float(getattr(self.camera, 'cairo_line_width_multiple', 0.01))
        pad = clearance + (float(shape.get_stroke_width()) * stroke_unit / 2 if stroke else 0)
        left, right, bottom, top = left - pad, right + pad, bottom - pad, top + pad
        if (shape.get_right()[0] < left or shape.get_left()[0] > right
                or shape.get_top()[1] < bottom or shape.get_bottom()[1] > top):
            return False
        cache = getattr(self, '_guard_geometry', {{}})
        key = id(shape)
        if key not in cache:
            segments = []
            for path in shape.get_subpaths():
                curves = shape.get_cubic_bezier_tuples_from_points(path)
                # Subdivide each actual cubic; connecting control points instead
                # would miss bowed curves and report strokes that do not exist.
                for curve in curves:
                    length = np.linalg.norm(np.diff(curve, axis=0), axis=1).sum()
                    count = min(128, max(8, int(length / 0.03) + 1))
                    t = np.linspace(0, 1, count + 1)[:, None]
                    samples = ((1-t)**3 * curve[0] + 3*(1-t)**2*t * curve[1]
                               + 3*(1-t)*t**2 * curve[2] + t**3 * curve[3])[:, :2]
                    segments.extend(np.stack((samples[:-1], samples[1:]), axis=1))
                if fill and len(path):
                    # A fill implicitly closes its subpath.
                    segments.append(np.array([path[-1, :2], path[0, :2]]))
            cache[key] = np.array(segments)
        segments = cache[key]
        if self._segments_cross_box(segments, left, right, bottom, top):
            return True
        if fill and len(segments):
            # Nonzero winding fill at the label centre; an edge entering the
            # label was already caught above, including small filled objects.
            x, y = (left + right) / 2, (bottom + top) / 2
            a, b = segments[:, 0], segments[:, 1]
            cross = (b[:, 0]-a[:, 0])*(y-a[:, 1]) - (x-a[:, 0])*(b[:, 1]-a[:, 1])
            winding = np.count_nonzero((a[:, 1] <= y) & (b[:, 1] > y) & (cross > 0))
            winding -= np.count_nonzero((a[:, 1] > y) & (b[:, 1] <= y) & (cross < 0))
            return bool(winding)
        return False

    def _guard_clear(self, m, texts, shapes, bounds=None):
        """Check a candidate label without moving any existing scene objects."""
        l, r, b, u = m.get_left()[0], m.get_right()[0], m.get_bottom()[1], m.get_top()[1]
        fx, fy = config.frame_width / 2, config.frame_height / 2
        bounds = bounds or getattr(self, '_grid_bounds', (-fx + _PAD_X, fx - _PAD_X, -fy + _PAD_Y, fy - _PAD_Y))
        if l < bounds[0] or r > bounds[1] or b < bounds[2] or u > bounds[3]:
            return False
        for other in texts:
            if other is m:
                continue
            if (min(r + 0.08, other.get_right()[0]) > max(l - 0.08, other.get_left()[0])
                    and min(u + 0.08, other.get_top()[1]) > max(b - 0.08, other.get_bottom()[1])):
                return False
        return not any(self._shape_crosses_box(s, l, r, b, u, clearance=0.06) for s in shapes)

    def _annotation_penalty(self, m, texts, bounds=None):
        """How bad a candidate label box is, used only when none is fully clear.

        Deliberately bbox-only. This runs for every rejected candidate (up to 36
        per call), so sampling stroke geometry here -- which is what
        `_shape_crosses_box` does -- made dense scenes miss the render timeout
        entirely. Choosing the least bad of several bad positions does not need
        that precision, and any geometry the label ends up crossing is still
        measured and reported by the guard afterwards.
        """
        l, r, b, u = m.get_left()[0], m.get_right()[0], m.get_bottom()[1], m.get_top()[1]
        fx, fy = config.frame_width / 2, config.frame_height / 2
        bounds = bounds or getattr(self, '_grid_bounds', (-fx + _PAD_X, fx - _PAD_X, -fy + _PAD_Y, fy - _PAD_Y))
        score = 0.0
        for value, limit, sign in ((l, bounds[0], 1.0), (r, bounds[1], -1.0),
                                   (b, bounds[2], 1.0), (u, bounds[3], -1.0)):
            outside = (limit - value) * sign
            if outside > 0:
                score += 100.0 + outside * 10.0
        for other in texts:
            if other is m:
                continue
            ix = min(r, other.get_right()[0]) - max(l, other.get_left()[0])
            iy = min(u, other.get_top()[1]) - max(b, other.get_bottom()[1])
            if ix > 0 and iy > 0:
                score += 10.0 + ix * iy
        return score

    def annotate(self, target, text, direction=RIGHT, accent=None, buff=0.18, obstacles=()):
        """Create a nearby label and leader that follow their target.

        Call after placing the complete diagram. Pass planned future geometry
        through obstacles; create a fresh annotation for a copied target. Remove
        the old annotation when replacing a state. Does not add anything to scene.
        """
        tag = label(text, 0.8, accent or MUTED_COLOR)
        texts = self._texts()
        shapes = self._occluders()
        pending = getattr(self, '_pending_annotations', [])
        visible_ids = {{id(m) for root in self.mobjects for m in root.get_family()}}
        # Reserve labels created together, but release them once displayed. This
        # avoids treating labels from a previous, removed state as obstacles.
        pending = [ref for ref in pending if ref() is not None and id(ref()) not in visible_ids]
        texts.extend(ref()[1] for ref in pending)
        for root in (target, *obstacles):
            for m in root.get_family():
                if isinstance(m, _TEXT_TYPES):
                    texts.append(m)
                elif m.has_points() and not getattr(m, '_edu_decor', False):
                    shapes.append(m)
        self._guard_geometry = {{}}
        bounds = getattr(target, '_edu_annotation_bounds', None)
        preferred = np.array(direction, dtype=float)
        preferred /= max(np.linalg.norm(preferred), 1e-6)
        ways = [preferred, RIGHT, LEFT, UP, DOWN, UR / np.sqrt(2), UL / np.sqrt(2), DR / np.sqrt(2), DL / np.sqrt(2)]
        max_gap = min(getattr(self, '_grid_cell_w', 1.0), getattr(self, '_grid_cell_h', 1.0))
        gap = max(0.08, min(float(buff), max_gap))
        fallback = None
        for distance in (gap, min(max_gap, gap + 0.15), min(max_gap, gap + 0.3), max_gap):
            for way in ways:
                tag.next_to(target, way, buff=distance)
                clear = self._guard_clear(tag, texts, shapes, bounds=bounds)
                if not clear:
                    score = self._annotation_penalty(tag, texts, bounds=bounds)
                    if fallback is None or score < fallback[0]:
                        fallback = (score, tag.get_center().copy(), way)
                if clear:
                    # Check that the connector doesn't cross an unrelated label.
                    start, end = target.get_edge_center(way), tag.get_edge_center(-way)
                    segment = np.array([[start[:2], end[:2]]])
                    if any(self._segments_cross_box(segment, t.get_left()[0], t.get_right()[0],
                                                    t.get_bottom()[1], t.get_top()[1]) for t in texts):
                        continue
                    group = _FollowingAnnotation(target, tag, way, accent or MUTED_COLOR)
                    pending.append(_weakref.ref(group))
                    self._pending_annotations = pending
                    return group
        # No candidate was fully clear. A label that is hard to place is a layout
        # defect to REPORT, not a reason to destroy the scene: raising here threw
        # away every other animation step and rendered a placeholder slide, which
        # the reviewer could only fail for "nothing is visible". Place the least
        # obstructed candidate and let the measured finding carry the complaint.
        score, center, way = fallback
        tag.move_to(center)
        self._add('annotation_crowded', 'major',
                  'annotation %r had no fully clear position; it was placed at the least obstructed '
                  'spot instead. Reserve a label lane beside the diagram, remove the previous '
                  'label before revealing this one, or shorten the text.' % text,
                  [str(text)], float(getattr(self.renderer, 'time', 0.0)))
        group = _FollowingAnnotation(target, tag, way, accent or MUTED_COLOR)
        pending.append(_weakref.ref(group))
        self._pending_annotations = pending
        return group

    def _guard_check(self, label, persist=True):
        try:
            t = float(getattr(self.renderer, "time", 0.0))
            fx, fy = config.frame_width / 2, config.frame_height / 2
            texts = self._texts()
            # Audit the rendered pose without silently moving labels away from
            # their leaders or moving the fixed title/lecture column.
            self._guard_geometry = {{}}
            if label == "motion":
                texts = [m for m in texts if id(m) in self._guard_text_ids]
            else:
                self._guard_text_ids = {{id(m) for m in texts}}
            self._guard_steps += 1
            for m in texts:
                l, r = m.get_left()[0], m.get_right()[0]
                b, u = m.get_bottom()[1], m.get_top()[1]
                name = _label_of(m)
                if l < -fx or r > fx or b < -fy or u > fy:
                    self._add("text_out_of_frame", "blocker",
                              f"text '{{name}}' is cut off by the frame edge", [name], t)
                elif (l < -fx + _PAD_X * 0.5 or r > fx - _PAD_X * 0.5
                      or b < -fy + _PAD_Y * 0.5 or u > fy - _PAD_Y * 0.5):
                    self._add("text_out_of_frame", "major",
                              f"text '{{name}}' violates the safe padding", [name], t)
            for i in range(len(texts)):
                for j in range(i + 1, len(texts)):
                    a, b2 = texts[i], texts[j]
                    ix = min(a.get_right()[0], b2.get_right()[0]) - max(a.get_left()[0], b2.get_left()[0])
                    iy = min(a.get_top()[1], b2.get_top()[1]) - max(a.get_bottom()[1], b2.get_bottom()[1])
                    if ix <= 0 or iy <= 0:
                        continue
                    smaller = min(a.width * a.height, b2.width * b2.height)
                    ratio = (ix * iy) / smaller if smaller > 0 else 0.0
                    if ratio > 0.12:
                        na, nb = _label_of(a), _label_of(b2)
                        self._add("text_overlap", "blocker" if ratio > 0.35 else "major",
                                  f"text '{{na}}' overlaps text '{{nb}}' ({{int(ratio * 100)}}%)",
                                  sorted([na, nb]), t)
            shapes = self._occluders()
            for m in texts:
                tl, tr = m.get_left()[0], m.get_right()[0]
                tb, tu = m.get_bottom()[1], m.get_top()[1]
                for s in shapes:
                    owner = getattr(s, '_edu_label_ref', None)
                    if owner is not None and owner() is m:
                        continue
                    sl, sr = s.get_left()[0], s.get_right()[0]
                    sb, su = s.get_bottom()[1], s.get_top()[1]
                    if self._shape_crosses_box(s, tl, tr, tb, tu):
                        name = _label_of(m)
                        shape = type(s).__name__
                        self._add("text_occluded", "blocker",
                                  f"text '{{name}}' intersects drawn {{shape}} geometry: "
                                  f"label x {{tl:.2f}}..{{tr:.2f}}, y {{tb:.2f}}..{{tu:.2f}}; "
                                  f"shape x {{sl:.2f}}..{{sr:.2f}}, y {{sb:.2f}}..{{su:.2f}} "
                                  "-- reserve clear space beside its target with self.annotate; "
                                  "remove the previous state's labels before revealing replacements",
                                  [name, shape], t)
        except Exception as exc:
            # Swallowing this used to report a crashed guard as a clean scene --
            # the exact failure this component exists to prevent. Say so instead.
            self._guard_findings.append({{
                "kind": "guard_unreadable", "severity": "blocker",
                "message": "the layout guard raised while checking this scene, so it "
                           "is unchecked: " + repr(exc)[:300],
                "subjects": [], "at_seconds": None,
            }})
        if not persist:
            return
        try:
            with open("guard.json", "w", encoding="utf-8") as fh:
                _json.dump({{"findings": self._guard_findings,
                            "checked_steps": self._guard_steps,
                            "auto_moved": self._guard_moved,
                            "source": "manim-layout-guard"}}, fh, indent=2)
        except Exception:
            pass


class TeachingScene(_EduGuardScene):
    """Fixed lecture column and bounded 6x6 anchors adapted from Code2Video."""

    def setup_layout(self, title_text, lecture_lines, kicker=""):
        self.title = title_bar(title_text, kicker=kicker)
        _fit(self.title, SAFE_W, 1.0)
        self.title.to_corner(UL, buff=max(_PAD_X, _PAD_Y))
        self.add(self.title)

        left = -config.frame_width / 2 + _PAD_X
        right = config.frame_width / 2 - _PAD_X
        top = min(config.frame_height * (0.5 - LAYOUT_CONTENT_TOP_RATIO),
                  self.title.get_bottom()[1] - 0.36)
        bottom = config.frame_height * (0.5 - LAYOUT_CONTENT_BOTTOM_RATIO)
        lecture_w = SAFE_W * LAYOUT_TEXT_RATIO
        gap = SAFE_W * LAYOUT_GAP_RATIO
        divider_x = left + lecture_w + gap / 2
        stage_left = left + lecture_w + gap
        stage_w = min(right - stage_left, SAFE_W * LAYOUT_VISUAL_RATIO)
        right = stage_left + stage_w
        stage_h = top - bottom
        self._grid_bounds = (stage_left, right, bottom, top)
        self._grid_cell_w = stage_w / 6
        self._grid_cell_h = stage_h / 6
        self.grid = {{}}
        for i, row_name in enumerate("ABCDEF"):
            for j in range(6):
                self.grid[row_name + str(j + 1)] = np.array([
                    stage_left + (j + 0.5) * self._grid_cell_w,
                    top - (i + 0.5) * self._grid_cell_h, 0,
                ])

        divider = Line([divider_x, bottom, 0], [divider_x, top, 0],
                       color=MUTED_COLOR, stroke_width=1.3).set_opacity(0.24)
        stage_rule = Line([stage_left, bottom + self._grid_cell_h * 2, 0],
                          [right, bottom + self._grid_cell_h * 2, 0],
                          color=MUTED_COLOR, stroke_width=1).set_opacity(0.15)
        self.add(_decor(divider), _decor(stage_rule))

        # Five, not four: a key scene is planned with five lecture lines, and a
        # column that silently drops the fifth makes show_step(4, ...) raise.
        lines = [str(line) for line in lecture_lines][:5]
        self.lecture = VGroup()
        self._lecture_numbers = VGroup()
        slot_h = stage_h / max(len(lines), 1)
        # Fit the whole lecture column as one typography unit.  Fitting each
        # note independently makes short lines render large while multiline
        # notes shrink, which breaks the planner's shared board hierarchy.
        notes = []
        note_heights = []
        max_note_h = max(0.5, slot_h - 0.68)
        for i, line in enumerate(lines):
            number = label("%02d" % (i + 1), size=0.62, color=PRIMARY_COLOR)
            number.move_to([left + number.width / 2, top - i * slot_h - 0.20, 0])
            wrapped = _wrap_lecture(line, lecture_w)
            note = label(wrapped, size=0.69, color=MUTED_COLOR)
            notes.append((number, note))
            note_heights.append(note)

        common_scale = 1.0
        for note in note_heights:
            if note.width > lecture_w:
                common_scale = min(common_scale, lecture_w / note.width)
            if note.height > max_note_h:
                common_scale = min(common_scale, max_note_h / note.height)
        common_scale = max(0.1, common_scale)
        for number, note in notes:
            note.scale(common_scale)
            note.next_to(number, DOWN, buff=0.20, aligned_edge=LEFT)
            self._lecture_numbers.add(number)
            self.lecture.add(note)
        self.add(self._lecture_numbers, self.lecture)
        # The presentation template owns this small homepage character accent;
        # the generated construct body never needs to know about the asset.
        try:
            character = ImageMobject(CHARACTER_PATH)
            character.scale_to_fit_height(config.frame_height / 3)
            character.to_corner(DR, buff=max(_PAD_X, _PAD_Y))
            character.set_z_index(-1)
            self.add(character)
            # The corner it stands in is reserved: placements shrink away from it
            # instead of putting content behind a third of a frame of artwork.
            margin = 0.12
            self._reserved = (character.get_left()[0] - margin, character.get_right()[0] + margin,
                              character.get_bottom()[1] - margin, character.get_top()[1] + margin)
        except Exception:
            pass
        return self

    def _avoid_reserved(self, left, right, bottom, top):
        """Trim a placement box away from the reserved corner.

        Returns the largest of: the box with the reserved columns cut off, and the
        box with the reserved rows cut off — whichever keeps more room. A box that
        does not touch the corner comes back unchanged, and one that would be left
        too small to hold anything is returned as-is (the guard still reports what
        lands under the art, but nothing is squeezed to a sliver).
        """
        zone = getattr(self, "_reserved", None)
        if zone is None:
            return left, right, bottom, top
        zl, zr, zb, zt = zone
        if right <= zl or left >= zr or top <= zb or bottom >= zt:
            return left, right, bottom, top
        candidates = []
        if zl > left:                      # keep the part to the left of the art
            candidates.append((left, min(right, zl), bottom, top))
        if zt < top:                       # keep the part above it
            candidates.append((left, right, max(bottom, zt), top))
        usable = [box for box in candidates
                  if (box[1] - box[0]) > self._grid_cell_w * 0.8
                  and (box[3] - box[2]) > self._grid_cell_h * 0.8]
        if not usable:
            return left, right, bottom, top
        return max(usable, key=lambda box: (box[1] - box[0]) * (box[3] - box[2]))

    def place_at_grid(self, mobject, grid_pos, scale_factor=1.0):
        mobject.scale(scale_factor)
        _fit(mobject, self._grid_cell_w - 0.16, self._grid_cell_h - 0.16)
        centre = self.grid[grid_pos]
        half_w, half_h = self._grid_cell_w / 2, self._grid_cell_h / 2
        box = self._avoid_reserved(centre[0] - half_w, centre[0] + half_w,
                                   centre[1] - half_h, centre[1] + half_h)
        _fit(mobject, box[1] - box[0] - 0.16, box[3] - box[2] - 0.16)
        mobject.move_to([(box[0] + box[1]) / 2, (box[2] + box[3]) / 2, 0])
        mobject._edu_grid_area = [grid_pos, grid_pos]
        for member in mobject.get_family():
            member._edu_annotation_bounds = box
        return mobject

    def place_in_area(self, mobject, top_left, bottom_right, scale_factor=1.0):
        tl, br = self.grid[top_left], self.grid[bottom_right]
        if tl[0] > br[0] or tl[1] < br[1]:
            raise ValueError("Grid area must go from top-left to bottom-right")
        left = tl[0] - self._grid_cell_w / 2
        right = br[0] + self._grid_cell_w / 2
        bottom = br[1] - self._grid_cell_h / 2
        top = tl[1] + self._grid_cell_h / 2
        left, right, bottom, top = self._avoid_reserved(left, right, bottom, top)
        mobject.scale(scale_factor)
        _fit(mobject, right - left - 0.24, top - bottom - 0.24)
        mobject.move_to([(left + right) / 2, (bottom + top) / 2, 0])
        mobject._edu_grid_area = [top_left, bottom_right]
        for member in mobject.get_family():
            member._edu_annotation_bounds = (left, right, bottom, top)
        return mobject

    def show_step(self, index, *mobjects, run_time=0.8):
        if not 0 <= index < len(self.lecture):
            raise ValueError("Lecture line index is out of range")
        changes = [line.animate.set_color(TEXT_COLOR if i == index else MUTED_COLOR)
                   for i, line in enumerate(self.lecture)]
        changes.extend(number.animate.set_color(SECONDARY_COLOR if i == index else PRIMARY_COLOR)
                       for i, number in enumerate(self._lecture_numbers))
        self.play(*changes, run_time=min(run_time, 0.45))
        if mobjects:
            self.reveal(*mobjects, run_time=run_time)


class {cls}(TeachingScene):
    def construct(self):
{body}
'''


def _safe_class_name(name: str, fallback: str = "EduScene") -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_]", "", name or "") or fallback
    if cleaned[0].isdigit():
        cleaned = "S" + cleaned
    if cleaned.startswith("_") or cleaned in {"Scene", "_EduGuardScene", "TeachingScene"}:
        cleaned = fallback
    return cleaned


def _indent(code: str, spaces: int = 8) -> str:
    pad = " " * spaces
    lines = []
    for line in code.strip().splitlines():
        lines.append(pad + line if line.strip() else "")
    return "\n".join(lines) if lines else pad + "pass"


def assemble_script(
    body: str,
    style: StyleConfig,
    class_name: str = "EduScene",
    *,
    scene_label: str = "",
    scene_index: int = 0,
    scene_total: int = 0,
) -> str:
    # Every render path funnels through here, including bodies replayed from a
    # stored spec, so the escape repair belongs at this choke point.
    body = normalize_tex_escapes(body)
    validate_construct_body(body)
    return THEME_HEADER.format(
        bg=style.palette.background,
        primary=style.palette.primary,
        secondary=style.palette.secondary,
        text=style.palette.text,
        muted=style.palette.muted,
        danger=style.palette.danger,
        font=resolve_manim_font(style.typography.font_family),
        font_cache_key=manim_font_cache_key(style.typography.font_family),
        font_files=repr([str(path) for path in bundled_manim_fonts(style.typography.font_family)]),
        pad=style.layout.padding_px,
        base_size=float(style.typography.base_size.removesuffix("px")),
        heading_scale=style.typography.heading_scale,
        title_ratio=style.layout.title_ratio,
        content_top_ratio=style.layout.content_top_ratio,
        content_bottom_ratio=style.layout.content_bottom_ratio,
        text_ratio=style.layout.text_ratio,
        visual_ratio=style.layout.visual_ratio,
        content_gap_ratio=style.layout.content_gap_ratio,
        particles=AMBIENT_PARTICLES,
        scene_label=re.sub(r'["\\\n\r]', "", str(scene_label))[:60],
        scene_index=max(0, int(scene_index)),
        scene_total=max(0, int(scene_total)),
        character_path=str(character_asset_path(scene_label)),
        w=style.layout.width,
        h=style.layout.height,
        text_types=TEXT_TYPES,
        cls=_safe_class_name(class_name),
        body=_indent(body),
    )


# `\\` immediately followed by a letter is never valid TeX (the line-break command
# is followed by whitespace or `[`), so it is always a model over-escaping a raw
# string: r"\\tau" reaches LaTeX as a line break plus the word "tau".
#
# The same holds for the thin-space commands. r"10\\,\\mathrm{N}" reaches LaTeX as a
# line break followed by a literal comma, which is how a one-line formula came out
# shredded across four lines with stray commas down the left edge. A real `\\` line
# break is followed by whitespace, `[` or the end of the string, so requiring one of
# `,;:!` after it keeps this from touching a deliberate break.
_OVER_ESCAPED = re.compile(r"\\\\(?=[A-Za-z,;:!])")


class _FixTexEscapes(ast.NodeTransformer):
    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        if isinstance(node.value, str) and "\\\\" in node.value:
            fixed = _OVER_ESCAPED.sub(lambda _: "\\", node.value)
            if fixed != node.value:
                return ast.copy_location(ast.Constant(value=fixed), node)
        return node


def normalize_tex_escapes(body: str) -> str:
    """Undo double-escaped TeX commands in string literals."""
    try:
        tree = ast.parse(body, mode="exec")
    except SyntaxError:
        return body
    fixed = _FixTexEscapes().visit(tree)
    ast.fix_missing_locations(fixed)
    try:
        return ast.unparse(fixed)
    except Exception:
        return body


def sanitize_construct_body(body: str) -> str:
    """Strip fences, class wrappers and redundant imports; the header provides manim.*."""
    raw = (body or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
        if raw.lower().startswith("python"):
            raw = raw[6:].lstrip()

    kept: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            continue
        kept.append(line)
    # Bodies copied out of a method often keep their indentation on every line
    # except the first (which the model trimmed). Re-indent line 1 to match the
    # rest, then dedent the whole block.
    body_lines = [ln for ln in kept if ln.strip()]
    if len(body_lines) > 1:
        first_indent = len(body_lines[0]) - len(body_lines[0].lstrip())
        rest_indent = min(len(ln) - len(ln.lstrip()) for ln in body_lines[1:])
        if first_indent < rest_indent:
            idx = kept.index(body_lines[0])
            kept[idx] = " " * rest_indent + kept[idx].lstrip()
    cleaned = normalize_tex_escapes(textwrap.dedent("\n".join(kept)).strip())
    # Models sometimes return a whole class; unwrap the construct body.
    match = re.search(r"def construct\(self\):\n((?:[ \t]+.*\n?|\s*\n)+)", cleaned + "\n")
    if match and cleaned.lstrip().startswith(("class ", "def construct")):
        cleaned = textwrap.dedent(match.group(1)).strip()
    return cleaned or "pass"


def latex_available() -> bool:
    return bool(
        shutil.which("latex")
        or shutil.which("pdflatex")
        or shutil.which("xelatex")
        or shutil.which("lualatex")
    ) and bool(shutil.which("dvisvgm"))


_GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "zeta": "ζ",
    "eta": "η", "theta": "θ", "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ",
    "nu": "ν", "xi": "ξ", "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ",
    "upsilon": "υ", "phi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π",
    "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}
_SYMBOLS = {
    "times": "×", "cdot": "·", "div": "÷", "pm": "±", "mp": "∓",
    "approx": "≈", "neq": "≠", "ne": "≠", "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥",
    "ll": "≪", "gg": "≫", "equiv": "≡", "propto": "∝", "infty": "∞",
    "perp": "⊥", "parallel": "∥", "angle": "∠", "degree": "°", "circ": "°",
    "rightarrow": "→", "to": "→", "leftarrow": "←", "Rightarrow": "⇒", "Leftarrow": "⇐",
    "leftrightarrow": "↔", "Leftrightarrow": "⇔", "partial": "∂", "nabla": "∇",
    "sum": "Σ", "prod": "Π", "int": "∫", "sqrt": "√", "ldots": "…", "dots": "…", "cdots": "⋯",
}
# Control sequences that only affect spacing or font — drop the command, keep the argument.
_TRANSPARENT = ("mathrm", "mathbf", "mathit", "mathsf", "mathtt", "text", "textbf",
                "textit", "operatorname", "boldsymbol", "bm", "rm", "bf", "it", "displaystyle")
_SPACERS = ("quad", "qquad", ",", ";", ":", "!", " ", "\\")
_SUB = str.maketrans("0123456789+-=()aehijklmnoprstuvx", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ")
_SUP = str.maketrans("0123456789+-=()in", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁱⁿ")


def _brace_arg(text: str, i: int) -> tuple[str, int]:
    r"""Read a {...}, \command or single-character argument; returns (arg, next_i)."""
    while i < len(text) and text[i] == " ":
        i += 1
    if i >= len(text):
        return "", i
    if text[i] == "\\":                       # ^\circ, _\alpha — one whole command
        j = i + 1
        while j < len(text) and text[j].isalpha():
            j += 1
        return text[i:j], j
    if text[i] != "{":
        return text[i], i + 1
    depth, start = 0, i
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
        i += 1
    return text[start + 1:], len(text)


def _script(inner: str, table, marker: str) -> str:
    """Unicode sub/superscript when every character maps; otherwise keep the marker
    so `\tau_{\rm cw}` reads as "τ_cw" rather than the ambiguous "τcw"."""
    plain = _convert(inner)
    if not plain:
        return ""
    converted = plain.translate(table)
    if all(ord(ch) > 127 or ch == " " for ch in converted):
        return converted
    return plain if len(plain) == 1 and not plain.isalnum() else marker + plain


def _latex_to_plain(tex: str) -> str:
    """Convert a LaTeX fragment to readable Unicode for hosts without a working TeX.

    This runs both when no TeX toolchain exists and when a specific formula fails
    to compile, so it must never leak a backslash or a brace into the frame — a
    rendered "\\tau_{\\rm cw}" is worse than no formula at all.
    """
    return _convert(tex) or "equation"


def _convert(tex: str) -> str:
    """The recursive worker: no placeholder text, so nested empties stay empty."""
    text = str(tex or "")
    out: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            j = i + 1
            name = ""
            while j < len(text) and text[j].isalpha():
                name += text[j]
                j += 1
            if not name:                      # \, \; \! \{ \} \\ …
                symbol = text[j] if j < len(text) else ""
                out.append(" " if symbol in (",", ";", ":", " ", "\\") else
                           symbol if symbol in "{}%$&#_" else "")
                i = j + 1
                continue
            if name == "frac":
                num, j = _brace_arg(text, j)
                den, j = _brace_arg(text, j)
                out.append("%s/%s" % (_wrap(num), _wrap(den)))
            elif name == "sqrt":
                arg, j = _brace_arg(text, j)
                out.append("√" + _wrap(arg))
            elif name in _TRANSPARENT:
                arg, j = _brace_arg(text, j) if j < len(text) and text[j:j + 1] == "{" else ("", j)
                out.append(_convert(arg))
            elif name in _SPACERS:
                out.append(" ")
            elif name in _GREEK:
                out.append(_GREEK[name])
            elif name in _SYMBOLS:
                out.append(_SYMBOLS[name])
            else:
                # Unknown command: keep its argument, drop the command itself.
                if j < len(text) and text[j:j + 1] == "{":
                    arg, j = _brace_arg(text, j)
                    out.append(_convert(arg))
            i = j
            continue
        if ch == "_":
            arg, i = _brace_arg(text, i + 1)
            out.append(_script(arg, _SUB, "_"))
            continue
        if ch == "^":
            arg, i = _brace_arg(text, i + 1)
            out.append(_script(arg, _SUP, "^"))
            continue
        if ch in "{}$":
            i += 1
            continue
        if ch == "&":
            out.append(" ")
            i += 1
            continue
        out.append(ch)
        i += 1
    plain = re.sub(r"\s+", " ", "".join(out)).strip()
    # Nothing that still looks like markup may reach the frame.
    return plain.replace("\\", "").replace("{", "").replace("}", "")


def _wrap(fragment: str) -> str:
    """Parenthesise a fraction part only when it is a compound expression."""
    plain = _convert(fragment)
    return plain if len(plain) <= 2 or plain.isalnum() else f"({plain})"


class _Demathify(ast.NodeTransformer):
    """Rewrite MathTex/Tex for hosts without a LaTeX toolchain."""

    def visit_Assign(self, node: ast.Assign) -> ast.AST | list[ast.AST]:
        node = self.generic_visit(node)
        assert isinstance(node, ast.Assign)
        val = node.value
        if (
            isinstance(val, ast.Call)
            and isinstance(val.func, ast.Attribute)
            and val.func.attr in {"get_text", "get_tex"}
        ):
            brace = val.func.value
            plain = "label"
            if val.args and isinstance(val.args[0], ast.Constant):
                if isinstance(val.args[0].value, str):
                    plain = _latex_to_plain(val.args[0].value)
            text_call = ast.Call(
                func=ast.Name(id="Text", ctx=ast.Load()),
                args=[ast.Constant(value=plain)],
                keywords=[ast.keyword("font", ast.Name(id="TEXT_FONT", ctx=ast.Load()))],
            )
            assign = ast.Assign(targets=node.targets, value=text_call)
            target = node.targets[0]
            tip = ast.Expr(
                value=ast.Call(
                    func=ast.Attribute(value=brace, attr="put_at_tip", ctx=ast.Load()),
                    args=[target],
                    keywords=[],
                )
            )
            return [assign, tip]
        return node

    def visit_Call(self, node: ast.Call) -> ast.AST:
        node = self.generic_visit(node)
        assert isinstance(node, ast.Call)
        func = node.func
        if isinstance(func, ast.Name) and func.id in {"MathTex", "Tex"}:
            parts = [
                _latex_to_plain(a.value) for a in node.args
                if isinstance(a, ast.Constant) and isinstance(a.value, str)
            ]
            plain = " ".join(parts) or "equation"
            keep = [kw for kw in node.keywords if kw.arg in {"font_size", "color", "weight"}]
            keep.append(ast.keyword("font", ast.Name(id="TEXT_FONT", ctx=ast.Load())))
            return ast.Call(
                func=ast.Name(id="Text", ctx=ast.Load()),
                args=[ast.Constant(value=plain)],
                keywords=keep,
            )
        if isinstance(func, ast.Name) and func.id == "TransformMatchingTex":
            return ast.Call(
                func=ast.Name(id="Transform", ctx=ast.Load()), args=node.args, keywords=node.keywords,
            )
        if isinstance(func, ast.Attribute) and func.attr in {"set_color_by_tex", "set_color_by_tex_to_color_map"}:
            return func.value
        if isinstance(func, ast.Attribute) and func.attr in {"get_text", "get_tex"}:
            plain = "label"
            if node.args and isinstance(node.args[0], ast.Constant):
                if isinstance(node.args[0].value, str):
                    plain = _latex_to_plain(node.args[0].value)
            return ast.Call(
                func=ast.Name(id="Text", ctx=ast.Load()),
                args=[ast.Constant(value=plain)],
                keywords=[ast.keyword("font", ast.Name(id="TEXT_FONT", ctx=ast.Load()))],
            )
        if isinstance(func, ast.Attribute) and func.attr == "set_stroke_width":
            width = node.args[0] if node.args else ast.Constant(value=4)
            return ast.Call(
                func=ast.Attribute(value=func.value, attr="set_stroke", ctx=ast.Load()),
                args=[],
                keywords=[ast.keyword("width", width)],
            )
        return node


def demathify_construct_body(body: str) -> str:
    """Replace MathTex/Tex with Text so scenes can render without LaTeX."""
    cleaned = sanitize_construct_body(body)
    tree = ast.parse(cleaned, mode="exec")
    rewritten = _Demathify().visit(tree)
    ast.fix_missing_locations(rewritten)
    return ast.unparse(rewritten)


def validate_construct_body(body: str) -> None:
    """Reject imports, dynamic execution and file/network access before execution."""
    try:
        tree = ast.parse(body, mode="exec")
    except SyntaxError as exc:
        raise ValueError(f"Invalid Manim construct syntax: {exc}") from exc
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)):
            raise ValueError(f"Forbidden Manim syntax: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            raise ValueError(f"Forbidden Manim name: {node.id}")
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("__") or node.attr in FORBIDDEN_ATTRIBUTES:
                raise ValueError(f"Forbidden Manim attribute: {node.attr}")
        if isinstance(node, (ast.ClassDef,)):
            raise ValueError("Forbidden Manim syntax: class definition inside construct body")


def generate_construct(
    provider: Provider,
    brief: SceneBrief,
    style: StyleConfig,
    *,
    feedback: str = "",
    prior_body: str = "",
    repair_ops: list | None = None,
    narration_seconds: float | None = None,
    guard_lines: list[str] | None = None,
) -> _ManimBody:
    target = narration_seconds or brief.target_seconds or 12
    tex_note = (
        "LaTeX IS available: use MathTex(r'...') for formulas (keep them short)."
        if latex_available()
        else "LaTeX is NOT available: write formulas as plain Unicode Text, e.g. "
        "'τ = F × r⊥', 'F₁ · r₁ = F₂ · r₂'. Never use underscore/caret notation like F_L or x^2."
    )
    elements = "\n".join(f"  - {e}" for e in brief.key_elements) or "  (none listed)"
    steps = brief.animations or []
    lines = brief.lecture_lines or []
    plan = "\n".join(
        f"  Lecture line {index + 1}: {lines[index] if index < len(lines) else '(no line)'}\n"
        f"    animation: {step}"
        for index, step in enumerate(steps)
    ) or "  (none planned — derive one step per lecture line from the visual brief)"
    prompt = f"""\
SCENE ID: {brief.id}
TITLE: {brief.title}
NARRATION (spoken over this scene, {target:.0f}s): {brief.narration}
VISUAL BRIEF: {brief.visual_brief}
{layout_contract(style)}
PLANNED ELEMENT PLACEMENTS:
{scene_layout_text(brief)}
ANIMATION PLAN (one step per lecture line, in order):
{plan}
KEY ELEMENTS THAT MUST BE VISIBLE (the reviewer checks each):
{elements}
TARGET SECONDS: {target:.0f}
{tex_note}

STYLE TOKENS (already injected as globals):
  PRIMARY_COLOR={style.palette.primary}  SECONDARY_COLOR={style.palette.secondary}
  DANGER_COLOR={style.palette.danger}    MUTED_COLOR={style.palette.muted}
  TEXT_COLOR={style.palette.text}        BACKGROUND_COLOR={style.palette.background}
  TEXT_FONT={style.typography.font_family}  BASE_FONT_SIZE={style.typography.base_size}
  SAFE_W≈{max(1.0, 14.22 - 2 * style.layout.padding_px / style.layout.width * 14.22):.1f} units,
  SAFE_H≈{max(1.0, 8.0 - 2 * style.layout.padding_px / style.layout.height * 8.0):.1f} units
"""
    if prior_body.strip():
        prompt += (
            "\nPRIOR CONSTRUCT BODY (edit minimally; keep the parts that worked):\n"
            f"{prior_body.strip()}\n"
        )
    if repair_ops:
        prompt += "\nSTRUCTURED REPAIR OPS (apply these precisely):\n"
        for op in repair_ops:
            dump = op.model_dump() if hasattr(op, "model_dump") else op
            prompt += f"- {dump}\n"
    if guard_lines:
        prompt += "\nAUTOMATIC LAYOUT GUARD FINDINGS FROM THE LAST RENDER (fix all):\n"
        prompt += "\n".join(f"- {line}" for line in guard_lines) + "\n"
    retry_note = feedback
    last_error = ""
    for _ in range(2):
        attempt_prompt = prompt
        if retry_note:
            attempt_prompt += f"\nPREVIOUS REVIEW FEEDBACK (fix these issues):\n{retry_note}\n"
        spec = provider.chat_json(attempt_prompt, _ManimBody, system=CODE_SYSTEM, max_tokens=20000)
        cleaned = sanitize_construct_body(spec.construct_body)
        try:
            validate_construct_body(cleaned)
            return _ManimBody(
                construct_body=cleaned,
                scene_class_name=_safe_class_name(spec.scene_class_name),
            )
        except ValueError as exc:
            last_error = str(exc)
            retry_note = (f"{feedback}\n" if feedback else "") + (
                f"Previous construct body was rejected: {exc}. "
                "Return ONLY statements that go inside construct(self). "
                "Do NOT include import/from lines, class wrappers, or markdown."
            )
            print(f"    [manim] construct rejected ({exc}); retrying…")
    print(f"    [manim] using safe fallback after: {last_error}")
    return _ManimBody(construct_body=FALLBACK_BODY, scene_class_name="EduScene", fallback_reason=last_error)


def repair_from_stderr(provider: Provider, body: str, stderr: str) -> str:
    """One API repair pass driven by the Manim traceback."""
    prompt = f"""\
The following Manim construct() body failed at render time. Return a corrected
construct body that fixes the error while keeping the same teaching content.
Do not add imports, classes, file access, network access, or markdown.

STDERR (tail):
{stderr[-3500:]}

CONSTRUCT BODY:
{body}
"""
    repaired = provider.chat_json(prompt, _ManimBody, system=CODE_SYSTEM, max_tokens=20000)
    cleaned = sanitize_construct_body(repaired.construct_body)
    validate_construct_body(cleaned)
    return cleaned


def parse_guard_report(work_dir: Path) -> GuardReport:
    path = work_dir / "guard.json"
    if not path.is_file():
        return GuardReport(source="manim-layout-guard:missing")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        findings = [GuardFinding.model_validate(f) for f in data.get("findings", [])]
        return GuardReport(
            findings=findings,
            checked_steps=int(data.get("checked_steps", 0)),
            source=str(data.get("source", "manim-layout-guard")),
        )
    except Exception as exc:
        # An unreadable report used to come back empty, which reads downstream as
        # "the guard found nothing" -- a silent pass from the component whose whole
        # job is to fail loudly. Say what happened instead.
        report = GuardReport(source=f"manim-layout-guard:unreadable:{exc}")
        report.findings.append(GuardFinding(
            kind="guard_unreadable", severity="blocker",
            message=f"the layout guard wrote a report this build cannot read, so the "
                    f"scene is unchecked: {str(exc)[:300]}",
        ))
        return report


def _restricted_env() -> dict[str, str]:
    allowed = ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "FONTCONFIG_PATH", "TEXMFHOME")
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env.setdefault("HOME", str(Path.home()))
    # NumPy/BLAS size their thread pools from the HOST core count, which inside a
    # container is a lie: a pod capped at 14 CPUs still reports 128, so every
    # render spawned ~130 threads and `parallel` scenes multiplied that into
    # hundreds fighting over the quota. Rendering a scene is single-threaded work
    # in practice, so the pools only ever cost context switches and cgroup
    # throttling -- one scene took 40 minutes at 7% CPU efficiency this way.
    for pool in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        env[pool] = os.environ.get(pool, "1")
    return env


def _resource_limiter(timeout: int):
    def limit() -> None:
        try:
            import resource

            resource.setrlimit(resource.RLIMIT_CPU, (timeout * 4, timeout * 4 + 5))
            resource.setrlimit(resource.RLIMIT_FSIZE, (2_000_000_000, 2_000_000_000))
            resource.setrlimit(resource.RLIMIT_NOFILE, (1024, 1024))
        except Exception:
            pass

    return limit


def _run_restricted(
    cmd: list[str],
    work_dir: Path,
    *,
    timeout: int,
    container_image: str | None,
) -> tuple[subprocess.CompletedProcess[str], str]:
    if container_image and shutil.which("docker"):
        root = work_dir.resolve()
        mapped: list[str] = []
        for arg in cmd:
            try:
                path = Path(arg)
                if path.is_absolute() and path.is_relative_to(root):
                    mapped.append(str(Path("/work") / path.relative_to(root)))
                else:
                    mapped.append(arg)
            except (ValueError, OSError):
                mapped.append(arg)
        docker_cmd = [
            "docker", "run", "--rm", "--network", "none",
            "--cpus", "2", "--memory", "4g",
            "-v", f"{root}:/work", "-w", "/work", container_image, *mapped,
        ]
        return (
            subprocess.run(docker_cmd, capture_output=True, text=True, timeout=timeout),
            f"docker:{container_image}",
        )
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_restricted_env(),
            preexec_fn=_resource_limiter(timeout) if os.name == "posix" else None,
        )
    except subprocess.TimeoutExpired as exc:
        proc = subprocess.CompletedProcess(
            cmd, returncode=124,
            stdout=(exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""),
            stderr=f"Manim render timed out after {timeout}s",
        )
    return proc, "ast+restricted-subprocess"


def _find_mp4(work_dir: Path, scene_id: str) -> Path | None:
    # manim writes under media/videos/<file>/<quality>/
    candidates = list(work_dir.rglob(f"{scene_id}.mp4"))
    if candidates:
        return max(candidates, key=lambda p: p.stat().st_mtime)
    any_mp4 = list((work_dir / "media").rglob("*.mp4")) if (work_dir / "media").exists() else []
    return max(any_mp4, key=lambda p: p.stat().st_mtime) if any_mp4 else None


def manim_bin() -> str | None:
    """First usable `manim`: $EDUHARNESS_MANIM, then PATH, then the project venv.

    ``.render-env`` keeps Manim on the persistent volume, where it survives the
    host image being rebuilt -- a pip install into /usr does not.  Looking there
    means the pipeline works whether or not ``$STORE/env.sh`` was sourced.
    """
    override = os.environ.get("EDUHARNESS_MANIM", "").strip()
    if override and os.access(override, os.X_OK):
        return override
    found = shutil.which("manim")
    if found:
        return found
    here = Path(__file__).resolve()
    roots = [here.parents[2]]
    if len(here.parents) > 5:
        roots.append(here.parents[5] / "eduharness" / "eduharness")
    for root in roots:
        candidate = root / ".render-env" / "bin" / "manim"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def manim_available() -> bool:
    return manim_bin() is not None
