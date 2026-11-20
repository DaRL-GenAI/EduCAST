"""Inner Loop 2 — refine visual quality for rendering-broken segments.

Takes VisualIssues from the outer reviewer and rewrites visual_brief so the
next render attempt has better guidance. Narration is untouched, so audio
cache stays valid — only the visual cache needs clearing.
"""

from __future__ import annotations

from ..providers.base import Provider
from ..schema import LessonPlan, VisualIssue


def refine(
    provider: Provider,
    plan: LessonPlan,
    issues: list[VisualIssue],
) -> set[str]:
    """Rewrite visual_brief for broken segments. Returns dirty visual segment ids."""
    by_id = {s.id: s for s in plan.segments}
    dirty: set[str] = set()

    for issue in issues:
        seg = by_id.get(issue.segment_id)
        if seg is None:
            continue
        seg.visual_brief = _rewrite_brief(provider, seg, issue)
        dirty.add(seg.id)

    return dirty


def _rewrite_brief(provider: Provider, seg, issue: VisualIssue) -> str:
    return provider.chat(
        f"The '{seg.modality.value}' visual for this segment was rendered poorly. "
        "Rewrite the visual brief to guide the renderer toward a cleaner, "
        "more legible result. Describe only what to show.\n\n"
        f"Issue: {issue.issue}\n"
        f"Suggestion: {issue.suggestion}\n\n"
        f"Narration: {seg.narration}\n"
        f"Current brief: {seg.visual_brief}",
        max_tokens=400,
    )
