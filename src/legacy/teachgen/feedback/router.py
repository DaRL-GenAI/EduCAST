"""Critique -> targeted revision of the LessonPlan.

The router turns reviewer feedback into the smallest change that fixes it, so the
next loop iteration re-renders only what's broken instead of rebuilding the whole
video. It mutates the plan and returns the set of segment ids that must be redone;
the pipeline reuses cached audio/visuals for everything else.
"""

from __future__ import annotations

from ..providers.base import Provider
from ..schema import Critique, LessonPlan, Modality, ReviewResult, Segment


def apply(provider: Provider, plan: LessonPlan, review: ReviewResult) -> set[str]:
    """Apply actionable critiques in place. Returns segment ids needing re-render."""
    dirty: set[str] = set()
    by_id = {s.id: s for s in plan.segments}

    for c in review.critiques:
        if c.severity == "minor":
            continue  # don't burn another render round on cosmetics
        seg = by_id.get(c.segment_id) if c.segment_id else None
        if seg is None:
            continue  # whole-video notes are advisory; nothing targeted to redo

        if c.fix_action == "rewrite_narration":
            seg.narration = _rewrite_narration(provider, seg, c)
            dirty.add(seg.id)  # audio (and any timing-driven visual) must regen
        elif c.fix_action == "replan":
            seg.modality = _pick_alternative(seg.modality)
            seg.visual_brief = _rewrite_brief(provider, seg, c)
            dirty.add(seg.id)
        elif c.fix_action == "re_render":
            seg.visual_brief = _rewrite_brief(provider, seg, c)
            dirty.add(seg.id)
        elif c.fix_action == "adjust_timing":
            # Timing-only: nudge the target and let the compositor refit. Cheap path —
            # mark dirty only for animation, whose length is intrinsic.
            if seg.modality == Modality.ANIMATION:
                dirty.add(seg.id)

    return dirty


def _pick_alternative(current: Modality) -> Modality:
    """Conservative fallback ladder when the reviewer says the approach is wrong."""
    ladder = {
        Modality.ANIMATION: Modality.SLIDE,
        Modality.CONCEPT_IMAGE: Modality.SLIDE,
        Modality.SLIDE: Modality.CONCEPT_IMAGE,
    }
    return ladder[current]


def _rewrite_narration(provider: Provider, seg: Segment, c: Critique) -> str:
    return provider.chat(
        f"Rewrite this narration to fix the issue. Keep it 2-5 spoken sentences, "
        f"same topic and order.\n\nIssue: {c.issue}\nDetail: {c.detail}\n\n"
        f"Current narration: {seg.narration}",
        max_tokens=400,
    )


def _rewrite_brief(provider: Provider, seg: Segment, c: Critique) -> str:
    return provider.chat(
        f"Rewrite the visual brief for a '{seg.modality.value}' renderer to fix the "
        f"issue.\n\nIssue: {c.issue}\nDetail: {c.detail}\n\n"
        f"Narration: {seg.narration}\nCurrent brief: {seg.visual_brief}",
        max_tokens=400,
    )
