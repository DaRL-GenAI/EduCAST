"""Content -> LessonPlan: assign a modality and a visual brief to each segment.

This is the router that decides which of the three production paths renders each
beat. It owns the *only* outline in the system; code2video and TeachingMonster's
own outliners are bypassed — they are used purely as segment-level renderers.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..providers.base import Provider
from ..schema import LessonPlan, Modality, Segment
from .content_writer import TeachingContent

SYSTEM = """\
You are a visual director for teaching videos. For each spoken segment, choose the
ONE best way to render its visual, then write a concrete brief for that renderer.

Available renderers (choose by content type):
- "animation": code2video / Manim. Best for DEMONSTRATIONS, step-by-step DERIVATIONS,
  math transformations, processes that evolve over time, anything that benefits from
  motion. This is the workhorse — prefer it for most teaching content.
- "concept_image": one rendered illustration. Best for INTUITION, METAPHORS, or a
  single big idea that a static labelled diagram captures well.
- "slide": a single polished bulleted slide. RESERVED for the FINAL recap/summary
  segment ONLY — the closing "knowledge points" wrap-up.

HARD RULE: only the LAST segment may use "slide", and it generally should. EVERY other
segment MUST be "animation" or "concept_image" — never "slide". Lean toward "animation"
for mechanisms/processes and "concept_image" for intuition/metaphor.

For each segment output: modality, a visual_brief (what the renderer should make,
referencing the narration), a one-line rationale, and target_seconds (estimate from
the narration length, ~2.5 words/sec).

For concept_image briefs specifically: be concrete and visual — name the central
metaphor or diagram type, list the key labeled components (2-5 items), describe
the compositional flow (left-to-right, radial, top-down, etc.), and mention the
color mood or contrast style. Vague briefs produce vague images; rich briefs
produce rich illustrations.
"""


class _Routed(BaseModel):
    title: str
    modality: Modality
    visual_brief: str = Field(..., description="Concrete instruction for the chosen renderer")
    rationale: str = ""
    target_seconds: float = Field(..., description="Estimated spoken duration in seconds")


class _RoutingPlan(BaseModel):
    segments: list[_Routed]


def plan_lesson(provider: Provider, content: TeachingContent) -> LessonPlan:
    seg_blob = "\n\n".join(
        f"[{i+1}] {s.title}\n{s.narration}" for i, s in enumerate(content.segments)
    )
    prompt = (
        f"Topic: {content.topic}\nAudience: {content.audience}\n\n"
        f"Segments (in order):\n{seg_blob}\n\n"
        "Route every segment. Keep the same order and count."
    )
    routing = provider.chat_json(prompt, _RoutingPlan, system=SYSTEM, max_tokens=4000)

    # Zip routing decisions back onto the narration.
    segments: list[Segment] = []
    for i, draft in enumerate(content.segments):
        routed = routing.segments[i] if i < len(routing.segments) else None
        segments.append(
            Segment(
                id=f"seg{i+1}",
                title=draft.title,
                narration=draft.narration,
                modality=routed.modality if routed else Modality.ANIMATION,
                visual_brief=(routed.visual_brief if routed else draft.narration),
                rationale=(routed.rationale if routed else "fallback: routing missing"),
                target_seconds=(routed.target_seconds if routed else None),
            )
        )

    _enforce_slide_only_last(segments)

    return LessonPlan(
        topic=content.topic,
        audience=content.audience,
        objectives=content.objectives,
        segments=segments,
    )


def _enforce_slide_only_last(segments: list[Segment]) -> None:
    """Guarantee the rule the prompt only requests: slides exist solely as the final
    recap. Any non-final slide is demoted to a concept image; the last segment is
    promoted to a slide so the lesson always closes on a summary deck."""
    last = len(segments) - 1
    for i, seg in enumerate(segments):
        if i < last and seg.modality == Modality.SLIDE:
            seg.modality = Modality.CONCEPT_IMAGE
            seg.rationale = f"(demoted from slide: slides reserved for final recap) {seg.rationale}"
    if segments and segments[last].modality != Modality.SLIDE:
        segments[last].modality = Modality.SLIDE
        segments[last].rationale = f"(promoted to slide: final recap) {segments[last].rationale}"
