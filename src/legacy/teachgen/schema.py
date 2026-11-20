"""Data contracts — the spine of the system.

Stages talk to each other only through these objects, never through each
other's implementation details. That decoupling is what makes the renderers
swappable and the feedback loop able to target individual segments.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Modality(str, Enum):
    """Which production path renders a segment's visual."""

    ANIMATION = "animation"            # code2video / Manim — demos, derivations, process
    SLIDE = "slide"                    # make_slide / pptx — definitions, summaries, lists
    CONCEPT_IMAGE = "concept_image"    # text-to-image — intuition, metaphor, one big idea


class Segment(BaseModel):
    id: str = Field(..., description="Stable id, e.g. 'seg1'")
    title: str
    narration: str = Field(..., description="Spoken script for this segment (plain text)")
    modality: Modality = Field(..., description="Which renderer produces the visual")
    visual_brief: str = Field(..., description="Instruction handed to the chosen renderer")
    rationale: str = Field("", description="Why the planner picked this modality")
    target_seconds: Optional[float] = Field(
        None, description="Planner's rough duration hint; animation renderer aims for this"
    )
    hints: dict = Field(default_factory=dict, description="Renderer-specific extras")


class LessonPlan(BaseModel):
    """Phase-1 output. Fully human-inspectable JSON — the natural review checkpoint."""

    topic: str
    audience: str
    objectives: list[str]
    segments: list[Segment]


class VisualAsset(BaseModel):
    """Normalized renderer output. Either a timed video clip or a static image."""

    segment_id: str
    kind: Literal["video", "image"]
    path: str
    duration: Optional[float] = Field(
        None, description="Set for video; None for image (driven by narration audio)"
    )


class WordTiming(BaseModel):
    word: str
    start: float
    end: float


class NarrationAudio(BaseModel):
    segment_id: str
    path: str
    duration: float
    words: list[WordTiming] = Field(default_factory=list)


class Critique(BaseModel):
    """One issue raised by the MLLM reviewer watching the composited video."""

    segment_id: Optional[str] = Field(None, description="None = whole-video issue")
    severity: Literal["blocker", "major", "minor"]
    issue: str
    fix_action: Literal["replan", "rewrite_narration", "re_render", "adjust_timing"]
    detail: str = ""


class ReviewResult(BaseModel):
    critiques: list[Critique] = Field(default_factory=list)
    overall_score: float = Field(0.0, description="0-10, reviewer's holistic rating")
    summary: str = ""

    @property
    def has_blocking_issues(self) -> bool:
        return any(c.severity in ("blocker", "major") for c in self.critiques)


# ---------------------------------------------------------------------------
# Nested feedback loop — outer review + inner refinement contracts
# ---------------------------------------------------------------------------

class ContentIssue(BaseModel):
    """A plan-level problem: narration or visual_brief needs rewriting."""

    segment_id: str
    field: Literal["narration", "visual_brief"]
    issue: str
    suggestion: str


class VisualIssue(BaseModel):
    """A rendering-quality problem: the approach is right but the output looks bad."""

    segment_id: str
    issue: str
    suggestion: str


class OuterReview(BaseModel):
    """Holistic evaluation of the composited video, with issues pre-classified."""

    overall_score: float = Field(..., description="0–10 holistic rating")
    content_issues: list[ContentIssue] = Field(default_factory=list)
    visual_issues: list[VisualIssue] = Field(default_factory=list)
    summary: str = ""

    @property
    def needs_plan_fix(self) -> bool:
        return bool(self.content_issues)

    @property
    def needs_visual_fix(self) -> bool:
        return bool(self.visual_issues)
