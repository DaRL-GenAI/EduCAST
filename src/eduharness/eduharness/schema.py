"""Data contracts for the EduHarness pipeline.

Stages communicate only through these objects.
"""

from __future__ import annotations

from enum import Enum
import re
from pathlib import PurePosixPath
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_CSS_PX = re.compile(r"^(?:0|[1-9]\d{0,3})(?:\.\d+)?px$")
_SAFE_ID = re.compile(r"[^0-9A-Za-z_-]+")

Severity = Literal["blocker", "major", "minor"]
FixAction = Literal["patch_artifact", "re_render", "change_tool", "adjust_timing", "noop"]


def _relative_bundle_path(value: str | None) -> str | None:
    if value in (None, ""):
        return value
    normalized = str(value).replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("path must stay inside the run or bundle directory")
    return normalized


# --------------------------------------------------------------------------- Style
class Palette(BaseModel):
    """Default is `studio_light`, the palette the player chrome is built on."""

    background: str = "#FAFBF8"
    primary: str = "#356B8F"
    secondary: str = "#16734A"
    text: str = "#17201B"
    muted: str = "#66706A"
    danger: str = "#B4423D"

    @field_validator("*")
    @classmethod
    def valid_color(cls, value: str) -> str:
        if not _HEX_COLOR.fullmatch(value):
            raise ValueError("colors must use six-digit hex notation")
        return value.upper()


class Typography(BaseModel):
    font_family: str = "Inter"
    base_size: str = "16px"
    heading_scale: float = 1.25

    @field_validator("font_family")
    @classmethod
    def valid_font(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 80 or any(c in value for c in "\"'<>;{}\\\n\r"):
            raise ValueError("font_family contains unsafe characters")
        return value

    @field_validator("base_size")
    @classmethod
    def valid_base_size(cls, value: str) -> str:
        if not _CSS_PX.fullmatch(value):
            raise ValueError("base_size must be a CSS px length")
        return value


class LayoutSpec(BaseModel):
    safe_padding: str = "40px"
    width: int = Field(1920, ge=320, le=7680)
    height: int = Field(1080, ge=240, le=4320)
    # Renderer-neutral teaching board contract. The named anchors mirror
    # Code2Video's A1-F6 system, while the ratios let raster, DOM, and video
    # renderers reserve the same title/content/footer bands.
    grid_rows: Literal[6] = 6
    grid_cols: Literal[6] = 6
    title_ratio: float = Field(0.14, gt=0.05, lt=0.30)
    content_top_ratio: float = Field(0.18, gt=0.08, lt=0.45)
    content_bottom_ratio: float = Field(0.84, gt=0.60, lt=0.95)
    # Fixed presentation template: readable copy on the left third and the
    # animation filling the remaining two thirds without a centre gutter.
    text_ratio: float = Field(0.33, ge=0.20, le=0.45)
    visual_ratio: float = Field(0.63, ge=0.30, le=0.75)
    content_gap_ratio: float = Field(0.04, ge=0.01, lt=0.35)
    max_object_ratio: float = Field(0.78, gt=0.40, le=1.0)

    @field_validator("safe_padding")
    @classmethod
    def valid_padding(cls, value: str) -> str:
        if not _CSS_PX.fullmatch(value):
            raise ValueError("safe_padding must be a CSS px length")
        return value

    @model_validator(mode="after")
    def valid_regions(self) -> "LayoutSpec":
        if self.title_ratio >= self.content_top_ratio:
            raise ValueError("title band must end before the content band")
        if self.content_top_ratio >= self.content_bottom_ratio:
            raise ValueError("content band must have positive height")
        if self.text_ratio + self.visual_ratio + self.content_gap_ratio > 1.0:
            raise ValueError("text, visual, and gap ratios must fit in the canvas")
        if self.padding_px * 2 >= min(self.width, self.height):
            raise ValueError("safe padding must leave a visible canvas")
        if self.padding_px >= self.height * self.title_ratio:
            raise ValueError("safe padding must leave a visible title band")
        return self

    @property
    def padding_px(self) -> int:
        return int(float(self.safe_padding.removesuffix("px")))

    @property
    def anchor_rows(self) -> str:
        return "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[: self.grid_rows]

    @property
    def anchor_cols(self) -> str:
        return "".join(str(i) for i in range(1, self.grid_cols + 1))

    def contract_text(self) -> str:
        """Compact layout contract shared by planner and all render prompts."""
        return (
            f"{self.width}x{self.height} board; {self.grid_rows}x{self.grid_cols} "
            f"anchors {self.anchor_rows[0]}1-{self.anchor_rows[-1]}{self.anchor_cols[-1]}; "
            f"title band top {self.title_ratio:.0%}; content band "
            f"{self.content_top_ratio:.0%}-{self.content_bottom_ratio:.0%}; "
            f"text/lecture column {self.text_ratio:.0%}; visual column "
            f"{self.visual_ratio:.0%}; gap {self.content_gap_ratio:.0%}; "
            f"safe padding {self.safe_padding}; max object footprint "
            f"{self.max_object_ratio:.0%}."
        )

    def regions(self) -> dict[str, dict[str, float]]:
        pad = self.padding_px
        safe_width = self.width - 2 * pad
        top = self.height * self.content_top_ratio
        bottom = self.height * self.content_bottom_ratio
        return {
            "title": {"x": pad, "y": pad, "width": safe_width,
                      "height": self.height * self.title_ratio - pad},
            "lecture": {"x": pad, "y": top, "width": safe_width * self.text_ratio,
                        "height": bottom - top},
            "visual": {"x": pad + safe_width * (self.text_ratio + self.content_gap_ratio),
                       "y": top, "width": safe_width * self.visual_ratio, "height": bottom - top},
            "footer": {"x": pad, "y": bottom + pad * .25, "width": safe_width,
                       "height": max(1, self.height - bottom - pad * 1.25)},
        }

    def area_box(self, area: str) -> dict[str, float]:
        first, last = _grid_area(area)
        visual = self.regions()["visual"]
        cw, ch = visual["width"] / 6, visual["height"] / 6
        inset = min(cw, ch) * .08
        return {
            "x": visual["x"] + first[1] * cw + inset,
            "y": visual["y"] + first[0] * ch + inset,
            "width": (last[1] - first[1] + 1) * cw - 2 * inset,
            "height": (last[0] - first[0] + 1) * ch - 2 * inset,
        }


# Named boards. The planner picks a name; _sanitize pins the exact values so the
# rendered media and the player chrome can never drift apart.
THEMES: dict[str, dict[str, str]] = {
    "studio_light": {
        "background": "#FAFBF8", "primary": "#356B8F", "secondary": "#16734A",
        "text": "#17201B", "muted": "#66706A", "danger": "#B4423D",
    },
    "academic_dark": {
        "background": "#12161B", "primary": "#6FA8D6", "secondary": "#4FC08D",
        "text": "#ECF1F4", "muted": "#8A94A0", "danger": "#E0766F",
    },
}


class StyleConfig(BaseModel):
    theme: str = "studio_light"
    palette: Palette = Field(default_factory=Palette)
    typography: Typography = Field(default_factory=Typography)
    layout: LayoutSpec = Field(default_factory=LayoutSpec)


def layout_contract(style: StyleConfig) -> str:
    """Return the non-negotiable placement rules for a renderer prompt."""
    l = style.layout
    return (
        f"CANVAS LAYOUT CONTRACT: {l.contract_text()}\n"
        f"- Keep the title/kicker in the top {l.title_ratio:.0%} band.\n"
        f"- Keep fixed lecture lines in the left {l.text_ratio:.0%} of the safe width; "
        f"reserve the right {l.visual_ratio:.0%} column for the main visual/interactive object.\n"
        f"- Keep all content between {l.content_top_ratio:.0%} and "
        f"{l.content_bottom_ratio:.0%} of the frame; leave the footer band clear.\n"
        "- A character illustration is FIXED CHROME in the lower-right corner, drawn by "
        "the renderer on every board scene. It reaches into the footer band and the right "
        "edge of the result area by design. Do not place scene content behind it, and do "
        "not report it as an intruding object, an overlap, or something to move or remove "
        "-- it is not the scene's content. Judge only whether the scene's own elements "
        "stay readable beside it.\n"
        f"- Treat the visual column as a {l.grid_rows}x{l.grid_cols} anchor grid "
        f"({l.anchor_rows[0]}1-{l.anchor_rows[-1]}{l.anchor_cols[-1]}): one independent "
        "object per anchor/area, no overlapping labels, and no off-frame objects.\n"
        f"- Labels stay within one anchor cell of their object; groups occupy at most "
        f"{l.max_object_ratio:.0%} of the available area and must be scaled to fit."
        "\n- Rows A-F run top to bottom; columns 1-6 run left to right. "
        "The main visual uses A1-D6; the result uses E1-F6. "
        "Keep title and lecture size/position fixed; replace prior results in place."
        "\n- THE DRAWING COMES FIRST: A1-D6 is the drawing area and a manim scene must "
        "put a real non-text visual there (circuit, axes, geometry, chart). A scene "
        "whose visual column is only text rows is a slide, not a teaching visual.\n"
        "- LOOSE TEXT IS STACKED IN ROWS: a caption, formula or unit row that is NOT "
        "part of the drawing takes one full-width row band of whatever rows the "
        "drawing leaves (E1-E6, then F1-F6, or A1-A6 above it), in reading order, one "
        "item per row. Loose text never floats beside the drawing at an arbitrary "
        "height and two text items never share a row band. Labels that belong to the "
        "drawing stay attached to their part instead — they are not loose text."
    )


# --------------------------------------------------------------------------- Scenes
class SceneType(str, Enum):
    IMAGE = "image"
    MANIM = "manim"
    REMOTION = "remotion"
    INTERACTIVE = "interactive"


def _grid_area(value: str) -> tuple[tuple[int, int], tuple[int, int]]:
    if not re.fullmatch(r"[A-F][1-6]-[A-F][1-6]", value):
        raise ValueError("area must be two anchors such as A1-D6")
    a, b = value.split("-")
    first, last = (ord(a[0]) - 65, int(a[1]) - 1), (ord(b[0]) - 65, int(b[1]) - 1)
    if first[0] > last[0] or first[1] > last[1]:
        raise ValueError("grid area must run from top-left to bottom-right")
    return first, last


class SceneBrief(BaseModel):
    """Planner output for one scene (before rendering)."""

    id: str
    title: str
    narration: str = ""
    scene_type: SceneType
    visual_brief: str
    # 2–5 concrete things that MUST be visible for the scene to teach its point.
    # The reviewer checks each one; missing entries are blocking defects.
    key_elements: list[str] = Field(default_factory=list, max_length=8)
    lecture_lines: list[str] = Field(default_factory=list, max_length=5)
    # At most three scenes carry the lesson; they get five lecture lines and five
    # animation steps, everything else gets three. Spending the bigger budget
    # everywhere makes every scene equally shallow.
    key_scene: bool = False
    # One animation step per lecture line: what actually MOVES while that line is
    # the active one. Without it a generator answers a paragraph-shaped brief with
    # a static drawing and a swapped formula, which is where thin scenes come from.
    animations: list[str] = Field(default_factory=list, max_length=6)
    takeaway: str = Field("", max_length=200)
    visual_area: str = "A1-D6"
    result_area: str = "E1-F6"
    # Short teaching takeaway for image prompts and player captions.
    caption: str = ""
    rationale: str = ""
    target_seconds: Optional[float] = None
    # Interactive only: which parameterized template to fill
    template: Optional[str] = None
    template_hint: Optional[str] = None
    # Hybrid player: an interactive scene can pause a prior video at this time.
    # If omitted, it remains a standalone timeline node for backward compatibility.
    trigger_scene_id: Optional[str] = None
    trigger_at_seconds: Optional[float] = Field(default=None, ge=0)

    @field_validator("id", mode="before")
    @classmethod
    def safe_id(cls, value: Any) -> str:
        cleaned = _SAFE_ID.sub("_", str(value or "").strip()).strip("_")
        return cleaned[:96]

    @field_validator("key_elements", mode="before")
    @classmethod
    def clean_key_elements(cls, value: Any) -> list[str]:
        if not value:
            return []
        out = []
        for item in value:
            text = str(item or "").strip()
            if text:
                out.append(text[:160])
        return out[:8]

    @field_validator("lecture_lines")
    @classmethod
    def clean_lecture_lines(cls, values: list[str]) -> list[str]:
        return [line.strip() for line in values if line.strip()]

    @model_validator(mode="after")
    def valid_layout_areas(self) -> "SceneBrief":
        a, b = _grid_area(self.visual_area), _grid_area(self.result_area)
        if (max(a[0][0], b[0][0]) <= min(a[1][0], b[1][0])
                and max(a[0][1], b[0][1]) <= min(a[1][1], b[1][1])):
            raise ValueError("visual_area and result_area must not overlap")
        return self


def scene_layout_text(scene: SceneBrief) -> str:
    return (f"Fixed title: {scene.title}\nFixed lecture lines: {teaching_lines(scene)}\n"
            f"Main visual: {scene.visual_area}; result: {scene.result_area}\n"
            f"Takeaway: {scene.takeaway or scene.caption}")


def teaching_lines(scene: SceneBrief) -> list[str]:
    """Old checkpoints use their existing short teaching text until replanned."""
    if scene.lecture_lines:
        return scene.lecture_lines
    sentences = re.split(r"(?<=[.!?\u3002\uff01\uff1f])\s*", scene.narration.strip())
    return [line for line in sentences if line][:3] or [scene.caption or scene.title]


def teaching_board(style: StyleConfig, scene: SceneBrief) -> dict[str, Any]:
    """One measured board payload for raster, Manim, Remotion, and DOM renderers."""
    layout = style.layout
    regions = layout.regions()
    regions["main"] = layout.area_box(scene.visual_area)
    regions["result"] = layout.area_box(scene.result_area)
    base = float(style.typography.base_size.removesuffix("px")) * layout.height / 1080
    return {
        "width": layout.width, "height": layout.height,
        "title": scene.title, "lecture_lines": teaching_lines(scene),
        "takeaway": scene.takeaway or scene.caption,
        "visual_area": scene.visual_area, "result_area": scene.result_area,
        "regions": regions,
        "font": {"title": base * style.typography.heading_scale * 2.4,
                 "body": base * 1.9, "small": base * 1.2},
        "palette": style.palette.model_dump(), "font_family": style.typography.font_family,
    }


class LessonBlueprint(BaseModel):
    topic: str
    audience: str
    learning_goal: str
    objectives: list[str] = Field(default_factory=list)
    icap_level: str = "interactive"
    style: StyleConfig = Field(default_factory=StyleConfig)
    scenes: list[SceneBrief]


# --------------------------------------------------------------------------- Deterministic guards
GuardKind = Literal[
    "text_out_of_frame",
    "text_overlap",
    "text_occluded",
    # Static scan of the scene's own grid calls -- a source heuristic, kept apart
    # from the measured `text_overlap` because the latter is authoritative in
    # `_to_repair` regardless of severity.
    "grid_anchor_overlap",
    # `annotate` could not find a fully clear position and placed the label at the
    # least obstructed candidate instead of aborting the render. Reported, not
    # authoritative: the VLM judges from the frames whether it is actually
    # unreadable. Omitting it here made the whole guard report fail validation,
    # which marks the scene unchecked -- a blocker far worse than the crowding.
    "annotation_crowded",
    "guard_unreadable",
    "blank_frame",
    "duration_mismatch",
    "dom_overflow",
    "render_fallback",
    "missing_asset",
]


class GuardFinding(BaseModel):
    """One deterministic (non-LLM) check result attached to a rendered scene."""

    kind: GuardKind
    severity: Severity = "major"
    message: str
    at_seconds: Optional[float] = None
    subjects: list[str] = Field(default_factory=list)


class GuardReport(BaseModel):
    findings: list[GuardFinding] = Field(default_factory=list)
    checked_steps: int = 0
    source: str = ""

    def blocking(self) -> list[GuardFinding]:
        return [f for f in self.findings if f.severity == "blocker"]

    def flagged_seconds(self) -> list[float]:
        seen: list[float] = []
        for f in self.findings:
            if f.at_seconds is None:
                continue
            if all(abs(f.at_seconds - s) > 0.25 for s in seen):
                seen.append(round(f.at_seconds, 3))
        return seen

    def summary_lines(self) -> list[str]:
        lines = []
        for f in self.findings:
            when = f" @ {f.at_seconds:.1f}s" if f.at_seconds is not None else ""
            lines.append(f"[{f.severity}] {f.kind}{when}: {f.message}")
        return lines


# --------------------------------------------------------------------------- Tool outputs
class SuccessCondition(BaseModel):
    """Declarative marker owned by a trusted template renderer; never evaluated."""

    kind: Literal["template_default"] = "template_default"
    description: str = ""


class InteractiveParams(BaseModel):
    template: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    success_condition: SuccessCondition = Field(default_factory=SuccessCondition)
    instruction: str = ""
    normalization_warnings: list[str] = Field(default_factory=list)
    teaching_layout: dict[str, Any] = Field(default_factory=dict)

    @field_validator("success_condition", mode="before")
    @classmethod
    def migrate_success_condition(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"kind": "template_default", "description": value}
        return value or {"kind": "template_default"}


class RepairOp(BaseModel):
    """One minimal edit against a prior tool artifact."""

    target: str = Field(..., description="Field path, e.g. construct_body, bullets[0], parameters.x")
    op: Literal["replace", "set", "append_constraint"] = "replace"
    before: Optional[str] = None
    after: Optional[str] = None
    value: Any = None
    rationale: str = ""


class SceneRepair(BaseModel):
    """Structured VLM verdict + repair plan for one scene (diff-first, prose fallback).

    `blocking_issues` are hard defects or missing key elements: the scene fails.
    `minor_issues` are nits that never burn a repair round on their own.
    `issues` is kept as the flat union for older readers.
    """

    scene_id: str = ""
    scene_type: Optional[SceneType] = None
    passed: bool = False
    score: float = Field(0.0, ge=0, le=10)
    brief_adherence: float = Field(10.0, ge=0, le=10)
    severity: Severity = "major"
    fix_action: FixAction = "re_render"
    blocking_issues: list[str] = Field(default_factory=list)
    minor_issues: list[str] = Field(default_factory=list)
    missing_key_elements: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    ops: list[RepairOp] = Field(default_factory=list)
    fallback_instructions: str = ""
    review_error: bool = False

    @model_validator(mode="after")
    def merge_issue_lists(self) -> "SceneRepair":
        # Older records only carry `issues`; newer ones split them.
        if not self.issues:
            self.issues = [*self.blocking_issues, *self.minor_issues]
        elif not self.blocking_issues and not self.minor_issues:
            if self.passed:
                self.minor_issues = list(self.issues)
            else:
                self.blocking_issues = list(self.issues)
        return self

    def finalize(self, *, pass_score: float = 6.0) -> "SceneRepair":
        """Derive passed/severity/fix_action deterministically from the evidence."""
        blocking = [*self.blocking_issues]
        for element in self.missing_key_elements:
            note = f"Missing key element: {element}"
            if note not in blocking:
                blocking.append(note)
        self.blocking_issues = blocking
        self.issues = [*self.blocking_issues, *self.minor_issues]
        if self.review_error:
            self.passed = False
            self.severity = "blocker"
            self.fix_action = "re_render"
            return self
        self.passed = not self.blocking_issues and self.score >= pass_score
        if self.passed:
            self.severity = "minor"
            self.fix_action = "noop"
            return self
        if self.score < 4 or self.missing_key_elements:
            self.severity = "blocker"
        elif self.severity == "minor":
            self.severity = "major"
        if self.fix_action == "noop":
            self.fix_action = "patch_artifact" if self.ops else "re_render"
        return self

    def summary_text(self) -> str:
        parts = [f"score={self.score}", f"severity={self.severity}", f"action={self.fix_action}"]
        if self.blocking_issues:
            parts.append(f"blocking={self.blocking_issues}")
        if self.minor_issues:
            parts.append(f"minor={self.minor_issues}")
        if self.ops:
            parts.append(
                "ops=["
                + "; ".join(
                    f"{op.op}:{op.target}"
                    + (f" {op.rationale}" if op.rationale else "")
                    for op in self.ops
                )
                + "]"
            )
        if self.fallback_instructions:
            parts.append(self.fallback_instructions)
        return "; ".join(parts)

    def feedback_text(self) -> str:
        """Actionable text for the executor (no scores, only what to change)."""
        lines: list[str] = []
        for issue in self.blocking_issues:
            lines.append(f"- MUST FIX: {issue}")
        for issue in self.minor_issues[:3]:
            lines.append(f"- nice to have: {issue}")
        if self.fallback_instructions:
            lines.append(self.fallback_instructions)
        return "\n".join(lines)

    def needs_repair(self) -> bool:
        if self.passed or self.fix_action == "noop" or self.severity == "minor":
            return False
        return True


class PreparedScene(BaseModel):
    """Checkpoint produced by API preparation and consumed by local rendering."""

    scene_id: str
    scene_type: SceneType
    spec_path: Optional[str] = None
    asset_path: Optional[str] = None
    narration_path: Optional[str] = None
    narration_seconds: Optional[float] = None
    caption: str = ""
    template: Optional[str] = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    success_condition: SuccessCondition = Field(default_factory=SuccessCondition)
    instruction: str = ""
    feedback: str = ""
    repair: Optional[SceneRepair] = None
    attempt: int = Field(0, ge=0)
    debug: dict[str, Any] = Field(default_factory=dict)

    @field_validator("scene_id", mode="before")
    @classmethod
    def safe_scene_id(cls, value: Any) -> str:
        return _SAFE_ID.sub("_", str(value or "").strip()).strip("_")[:96]

    @field_validator("spec_path", "asset_path", "narration_path")
    @classmethod
    def safe_checkpoint_path(cls, value: str | None) -> str | None:
        return _relative_bundle_path(value)


class RenderedScene(BaseModel):
    scene_id: str
    scene_type: SceneType
    # Relative path inside the run dir (media/… or interactive/…)
    src: str
    duration: Optional[float] = None
    visual_seconds: Optional[float] = None
    audio_src: Optional[str] = None
    narration_seconds: Optional[float] = None
    template: Optional[str] = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    review_passed: bool = False
    review_notes: str = ""
    review_error: bool = False
    repair: Optional[SceneRepair] = None
    guard: GuardReport = Field(default_factory=GuardReport)
    render_mode: str = "native"
    debug: dict[str, Any] = Field(default_factory=dict)

    @field_validator("src")
    @classmethod
    def safe_src(cls, value: str) -> str:
        return _relative_bundle_path(value) or ""

    @field_validator("audio_src")
    @classmethod
    def safe_audio_src(cls, value: str | None) -> str | None:
        return _relative_bundle_path(value)


class ReviewVerdict(BaseModel):
    """Legacy flat verdict; prefer SceneRepair for repair loops."""

    passed: bool
    score: float = Field(ge=0, le=10)
    issues: list[str] = Field(default_factory=list)
    fix_instructions: str = ""
    review_error: bool = False

    def to_scene_repair(
        self,
        *,
        scene_id: str = "",
        scene_type: SceneType | None = None,
    ) -> SceneRepair:
        repair = SceneRepair(
            scene_id=scene_id,
            scene_type=scene_type,
            passed=self.passed,
            score=self.score,
            blocking_issues=[] if self.passed else list(self.issues),
            minor_issues=list(self.issues) if self.passed else [],
            fallback_instructions=self.fix_instructions,
            review_error=self.review_error,
        )
        return repair.finalize()


# --------------------------------------------------------------------------- Bundle / Manifest
class InteractiveOverlay(BaseModel):
    id: str
    trigger_at: float = Field(ge=0)
    template: str
    config_src: str
    title: str = ""
    audio_src: Optional[str] = None
    narration: str = ""

    @field_validator("config_src")
    @classmethod
    def safe_config_path(cls, value: str) -> str:
        return _relative_bundle_path(value) or ""

    @field_validator("audio_src")
    @classmethod
    def safe_overlay_audio(cls, value: str | None) -> str | None:
        return _relative_bundle_path(value)


class TimelineItem(BaseModel):
    id: str
    type: Literal["video", "image", "interactive"]
    src: Optional[str] = None
    audio_src: Optional[str] = None
    duration: Optional[float] = None
    trigger_at: Optional[float] = None
    template: Optional[str] = None
    config_src: Optional[str] = None
    title: str = ""
    narration: str = ""
    overlays: list[InteractiveOverlay] = Field(default_factory=list)

    @field_validator("src", "config_src", "audio_src")
    @classmethod
    def safe_timeline_path(cls, value: str | None) -> str | None:
        return _relative_bundle_path(value)


class Manifest(BaseModel):
    bundle_id: str
    topic: str
    style: StyleConfig
    timeline: list[TimelineItem]
    total_duration: float = 0.0
    # Hash of the timeline metadata and packaged media. Player resume snapshots
    # are scoped to this value so a same-name re-render cannot restore stale time.
    content_version: str = ""


class HarnessRequest(BaseModel):
    """Top-level user input."""

    request_id: str = "demo"
    topic: str
    audience: str = "undergraduate students"
    learning_goal: str = ""
    source_text: str = Field(
        "",
        description="Raw lecture notes / transcript / outline fed to Stage 1",
    )
    preferred_theme: str = "studio_light"
    language: str = Field("en", description="Narration / on-screen language hint")
    max_review_rounds: int = Field(3, ge=1, le=6)
    enable_remotion: bool = False
    enable_manim: bool = True
    enable_image: bool = True
    enable_narration: bool = True
    voice: str = "alloy"
    allow_unreviewed_bundle: bool = False
    parallel: int = Field(4, ge=1, le=16)
