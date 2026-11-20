"""Outer-loop reviewer: watches the full composited video and classifies issues.

Produces an OuterReview with:
  - overall_score      (0-10, triggers early-stop when >= cfg.score_threshold)
  - content_issues     → handled by Inner Loop 1 (plan_refiner)
  - visual_issues      → handled by Inner Loop 2 (visual_refiner)

The outer reviewer decides WHETHER each inner loop runs; the inner modules
decide HOW to fix what's broken.
"""

from __future__ import annotations

from pathlib import Path

from ..providers.base import Provider
from ..schema import LessonPlan, OuterReview
from ._frames import sample_frames

SYSTEM = """\
You are an expert educational video reviewer. Watch the full teaching video and
classify any issues into exactly two buckets:

CONTENT issues (plan-level) — fix by rewriting narration or visual_brief:
  • Narration is factually wrong, unclear, or mismatched to what is shown.
  • The visual_brief for a segment needs a better description (the approach is
    right, but the instructions were too vague or wrong).

VISUAL issues (rendering quality) — fix by re-rendering with improved guidance:
  • The visual output is broken, illegible, or aesthetically poor, but the
    overall approach (what to show) is correct.

Rules:
  • Only report blockers and major issues — skip cosmetic nitpicks.
  • field must be exactly "narration" or "visual_brief" for content issues.
  • Give an overall_score 0 (unwatchable) to 10 (publication-ready).
  • If there are no issues of a type, return an empty list for that bucket.
"""


def review(
    provider: Provider,
    plan: LessonPlan,
    video_path: Path,
    *,
    num_frames: int = 12,
) -> OuterReview:
    frames = sample_frames(video_path, num_frames)
    plan_blob = "\n".join(
        f"{s.id} [{s.modality.value}] {s.title}: {s.narration}"
        for s in plan.segments
    )
    prompt = (
        f"Topic: {plan.topic} (audience: {plan.audience})\n\n"
        f"Lesson plan:\n{plan_blob}\n\n"
        f"{len(frames)} frames follow in chronological order. Review the video."
    )
    notes = provider.vision(prompt, frames, system=SYSTEM, max_tokens=2000)
    return provider.chat_json(
        f"Convert this review into the OuterReview schema:\n\n{notes}",
        OuterReview,
        system="Convert free-form review notes into the OuterReview schema verbatim.",
        max_tokens=2000,
    )
