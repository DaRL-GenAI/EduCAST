"""Inner Loop 1 — refine the lesson plan based on content issues.

Only `narration` and `visual_brief` can change; modality and segment structure
are frozen. Returns two disjoint dirty sets so the pipeline knows what to
invalidate:

  dirty_full         narration changed → re-TTS + re-render (both caches cleared)
  dirty_visual_only  only visual_brief changed → re-render only (audio reused)
"""

from __future__ import annotations

from ..providers.base import Provider
from ..schema import ContentIssue, LessonPlan


def refine(
    provider: Provider,
    plan: LessonPlan,
    issues: list[ContentIssue],
) -> tuple[set[str], set[str]]:
    """Apply content fixes in-place. Returns (dirty_full, dirty_visual_only)."""
    by_id = {s.id: s for s in plan.segments}
    dirty_full: set[str] = set()
    dirty_visual: set[str] = set()

    for issue in issues:
        seg = by_id.get(issue.segment_id)
        if seg is None:
            continue

        if issue.field == "narration":
            seg.narration = _rewrite_narration(provider, seg.narration, issue)
            dirty_full.add(seg.id)
        elif issue.field == "visual_brief":
            seg.visual_brief = _rewrite_brief(provider, seg, issue)
            dirty_visual.add(seg.id)

    dirty_visual -= dirty_full   # narration-dirty segments already cover the visual
    return dirty_full, dirty_visual


def _rewrite_narration(provider: Provider, current: str, issue: ContentIssue) -> str:
    return provider.chat(
        "Rewrite this narration to fix the issue. Keep it 2-5 spoken sentences "
        "on the same topic and in the same teaching order.\n\n"
        f"Issue: {issue.issue}\n"
        f"Suggestion: {issue.suggestion}\n\n"
        f"Current narration:\n{current}",
        max_tokens=400,
    )


def _rewrite_brief(provider: Provider, seg, issue: ContentIssue) -> str:
    return provider.chat(
        f"Rewrite the visual brief for a '{seg.modality.value}' renderer. "
        "Describe only what to show — not how to narrate it.\n\n"
        f"Issue: {issue.issue}\n"
        f"Suggestion: {issue.suggestion}\n\n"
        f"Narration: {seg.narration}\n"
        f"Current brief: {seg.visual_brief}",
        max_tokens=400,
    )
