"""Stage 1 — Main Agent: lesson split + central style board."""

from __future__ import annotations

from ..providers.base import Provider
from ..schema import (
    THEMES, HarnessRequest, LayoutSpec, LessonBlueprint, Palette, SceneBrief, SceneType,
    StyleConfig, teaching_lines,
)
from ..templates import registry

SYSTEM = """\
You are the Main Agent (总导演) of an interactive teaching-media pipeline.

Given raw teaching assets (notes / transcript / outline) OR a topic + audience,
produce a LessonBlueprint that downstream tools can render WITHOUT further
interpretation.

1. Split content into ordered Scenes (typically 5–8, each 15–40 s of narration).
2. Route each scene to exactly one scene_type:
   - image: a complete static teaching diagram, concept metaphor or intuition scene.
     A text model expands the brief, then gpt-image-2 generates the diagram with
     at most 3-5 short readable labels, a clear visual flow and generous whitespace.
     Name the central concept, key labelled components and the teaching takeaway.
   - manim: formula derivations, labelled geometry, graphs, step-by-step
     processes (2D vector graphics with text labels).
   - remotion: title card, bullets, a highlighted formula card, a two-column
     compare, numbered steps, or a recap (bullets + formula card) — typographic
     motion graphics with fixed layouts.
   - interactive: nodes where the student must construct / practice /
     self-check (ICAP). Use ONE of the templates listed below; put concrete
     values for its parameters in template_hint.
3. Include at least ONE interactive scene after the core concept is taught.
   When it should interrupt an earlier manim/remotion video, set
   trigger_scene_id to that scene id and trigger_at_seconds strictly inside
   that scene's target_seconds; otherwise leave both null.
4. Plan content only. The host applies one fixed presentation template after
   planning: title at the top, copy in the left third, animation in the right
   two thirds, and the homepage character accent in the lower-right corner.
   A manim scene MUST have a real drawing (circuit, axes, geometry, chart) as its
   visual anchor — a visual column made only of text rows is a slide, and the
   lecture column already carries the words. Plan the drawing first, then stack the
   loose text: a caption, formula or unit row that is not part of the drawing takes
   one full-width row of whatever rows the drawing leaves, in reading order, one
   item per row, never floating beside the drawing at an arbitrary height and never
   two items in one row. Labels belonging to the drawing stay attached to their
   part; they are not loose text. Name the object each annotation belongs to and
   reserve clear space immediately outside that object or in a compact annotation
   column adjoining the drawing. Keep labels close enough to identify their
   objects, with short leader lines when needed, and never across curves, axes,
   arrow shafts/tips, or another label. Reserve space for the full motion path
   and for every comparison state, not just the initial frame. Do not
   invent colours, ratios, coordinates, or renderer-specific layout. A Remotion
   title_card is a clean full-frame opener, and an interactive scene is a
   standalone practice panel. Image scenes are complete concept illustrations;
   these three formats do not get the ordinary template chrome.
5. visual_brief must be concrete and renderer-ready: what is drawn, where,
   in which palette role (primary/secondary/danger/muted/text), and in what order.
   Design a composed teaching frame, not an isolated bullet list: title treatment,
   a dominant visual anchor, 2-4 supporting details, and a clear takeaway.
   For animations specify 3-5 meaningful visual states (setup, change, comparison,
   result) so the scene teaches through motion instead of only fading text in.
   In visual_brief describe which labels belong to each state and which clear
   side of the drawing or adjoining annotation column they occupy; the host
   resolves the exact positions and typography.
6. key_elements: 2–5 short, checkable statements of what MUST be visible
   (e.g. "lever with fulcrum triangle", "equation τ = F × r", "both torque values").
   An automated visual reviewer fails the scene if any is missing, so list
   only things the chosen tool can actually show, and describe WHAT must be
   visible, never WHERE or in what style ("equation τ = F × r", not "formula
   card on the right with a glow"). Positions belong in visual_brief. For
   interactive scenes list only what is visible BEFORE the student answers
   (the prompt, the controls), never the feedback or explanation. Remotion
   beats are typographic: never list drawings/silhouettes as key elements
   there — route drawings to manim.
   Mark AT MOST THREE scenes as `key_scene: true` — the ones that carry the lesson.
   A key scene gets 5 `lecture_lines` and 5 `animations`; every other scene gets 3
   and 3. Emit short `lecture_lines` (plain teaching sentences, not audit criteria)
   and a concise `takeaway`. For manim and remotion scenes also emit `animations`:
   ONE step per lecture line, in the same order, naming what MOVES while that line
   is the active one ("the current arrow slides along the wire and the resistor box
   flashes", not "show the circuit"). A step that draws something and leaves it
   there is not a step — say what changes, appears, transforms or fades. The
   scene's visual must teach through those steps, so each one has to be worth a
   second of screen time. Each animations step must also say which annotations
   update, move with their object, or disappear. Replace or remove the previous
   state's labels before showing new ones, unless an explicit comparison keeps
   both objects and their separate labels visible. A shared label such as
   "y-intercept" appears once; changing values update its associated annotation.
   The host fixes all visual areas after planning. For
   practice, lecture_lines explain the task without revealing the answer and
   takeaway must not give away the solution.
7. narration: the spoken teacher voice for the scene, 2–4 plain sentences,
   written in the requested language. target_seconds ≈ narration length
   (about 2.6 words per second).
8. Do not spend planning effort on palette, ratios, coordinates, or card chrome.
   The host pins those values after this content plan is returned.
"""


def plan_lesson(provider: Provider, request: HarnessRequest) -> LessonBlueprint:
    source = request.source_text.strip() or (
        f"Topic: {request.topic}\n"
        f"Audience: {request.audience}\n"
        f"Learning goal: {request.learning_goal or 'Teach the topic clearly.'}"
    )
    prompt = f"""\
REQUEST_ID: {request.request_id}
TOPIC: {request.topic}
AUDIENCE: {request.audience}
LEARNING_GOAL: {request.learning_goal or "(derive from source)"}
LANGUAGE: {request.language}
PREFERRED_THEME: {request.preferred_theme}
ENABLE_MANIM: {request.enable_manim}
ENABLE_REMOTION: {request.enable_remotion}
ENABLE_IMAGE: {request.enable_image}

SOURCE MATERIAL:
---
{source}
---

The host owns one fixed presentation template for ordinary media: title at the
top, copy on the left third, animation on the right two thirds, and a small
lower-right character accent. A Remotion title_card and interactive scenes are
the two exceptions. Plan the teaching content only; the host resolves all
geometry and style.

INTERACTIVE TEMPLATES (id: description + parameters):
{registry.catalog_for_prompt()}

Rules:
- If ENABLE_MANIM is false, never use scene_type=manim (use image or remotion instead).
- If ENABLE_REMOTION is false, never use scene_type=remotion.
- If ENABLE_IMAGE is false, never use scene_type=image (use manim or remotion for intuition scenes).
- Scene ids: short kebab-case like "s1-title".
- Output a complete LessonBlueprint JSON (including style).
"""
    blueprint = provider.chat_json(
        prompt, LessonBlueprint, system=SYSTEM, max_tokens=9000, effort="high"
    )
    return _sanitize(blueprint, request)


def _sanitize(bp: LessonBlueprint, request: HarnessRequest) -> LessonBlueprint:
    if not bp.topic:
        bp.topic = request.topic
    if not bp.audience:
        bp.audience = request.audience
    if not bp.style:
        bp.style = StyleConfig(theme=request.preferred_theme)
    # Pin the palette to the named board so media and chrome stay one system.
    board = THEMES.get(bp.style.theme) or THEMES.get(request.preferred_theme)
    if board:
        bp.style.palette = Palette(**board)
        if bp.style.theme not in THEMES:
            bp.style.theme = request.preferred_theme
    # The host owns the palette and geometry. The plan contributes content only.
    bp.style.layout = LayoutSpec()

    valid_templates = set(registry.list_templates())
    prior_video: dict[str, float] = {}
    for index, sc in enumerate(bp.scenes):
        if sc.scene_type == SceneType.MANIM and not request.enable_manim:
            sc.scene_type = SceneType.IMAGE
            sc.rationale = (sc.rationale or "") + " [demoted: manim disabled]"
        if sc.scene_type == SceneType.REMOTION and not request.enable_remotion:
            sc.scene_type = SceneType.IMAGE if request.enable_image else SceneType.MANIM
            sc.rationale = (sc.rationale or "") + " [demoted: remotion disabled]"
        if sc.scene_type == SceneType.IMAGE and not request.enable_image:
            sc.scene_type = SceneType.REMOTION if request.enable_remotion else SceneType.MANIM
            sc.rationale = (sc.rationale or "") + " [demoted: image disabled]"
        if sc.scene_type == SceneType.INTERACTIVE:
            if not sc.template or sc.template not in valid_templates:
                sc.template = "multiple_choice"
            target = prior_video.get(sc.trigger_scene_id or "")
            if sc.trigger_scene_id and target is None:
                sc.trigger_scene_id = None
                sc.trigger_at_seconds = None
            elif sc.trigger_scene_id and target is not None:
                if sc.trigger_at_seconds is None or sc.trigger_at_seconds >= target:
                    sc.trigger_at_seconds = max(0.5, round(target * 0.9, 1))
        else:
            sc.template = None
            sc.template_hint = None
            sc.trigger_scene_id = None
            sc.trigger_at_seconds = None
        if not sc.id:
            sc.id = f"scene_{index + 1}"
        if not sc.key_elements:
            sc.key_elements = [sc.title]
        if not sc.lecture_lines:
            sc.lecture_lines = teaching_lines(sc)
        _align_animation_steps(sc)
        if not sc.takeaway and sc.scene_type != SceneType.INTERACTIVE:
            sc.takeaway = sc.caption or sc.lecture_lines[-1]
        sc.visual_area = "A1-D6"
        sc.result_area = "E1-F6"
        if sc.scene_type == SceneType.IMAGE and not sc.caption:
            sc.caption = sc.title
        if sc.target_seconds is None or sc.target_seconds <= 0:
            words = len((sc.narration or "").split())
            sc.target_seconds = float(max(6, round(words / 2.6 + 2)))
        if sc.scene_type in (SceneType.MANIM, SceneType.REMOTION):
            prior_video[sc.id] = float(sc.target_seconds or 10.0)

    seen: set[str] = set()
    for i, sc in enumerate(bp.scenes):
        if sc.id in seen:
            sc.id = f"{sc.id}_{i + 1}"
        seen.add(sc.id)
    if bp.scenes:
        _shape_opener(bp.scenes[0])
    _cap_key_scenes(bp)
    return bp


def _cap_key_scenes(bp: LessonBlueprint, limit: int = 3) -> None:
    """Keep the bigger budget scarce: the first `limit` key scenes keep it.

    A plan that marks everything key spends five steps on the recap and the title
    as well, which is how a lesson ends up uniformly shallow instead of having a
    few scenes that actually teach.
    """
    kept = 0
    for scene in bp.scenes:
        if not scene.key_scene:
            continue
        if kept < limit and scene.scene_type in (SceneType.MANIM, SceneType.REMOTION):
            kept += 1
            continue
        scene.key_scene = False
        _align_animation_steps(scene)


def _align_animation_steps(scene: SceneBrief) -> None:
    """Keep one animation step per lecture line, in order.

    The renderer prompt pairs them up (step N drives lecture line N), so a plan
    with four steps for three lines silently drops one and a plan with none turns
    the scene back into a still drawing.
    """
    if scene.scene_type not in (SceneType.MANIM, SceneType.REMOTION):
        scene.animations = []
        return
    steps = [str(step).strip() for step in scene.animations if str(step).strip()]
    budget = 5 if scene.key_scene else 3
    scene.lecture_lines = scene.lecture_lines[:budget]
    lines = scene.lecture_lines
    if not lines:
        scene.animations = steps[:budget]
        return
    if len(steps) > len(lines):
        steps = steps[:len(lines)]
    while len(steps) < len(lines):
        # A missing step is better stated than invented: name the line it belongs
        # to so the renderer still has to animate something for it.
        steps.append(f"Bring the visual for '{lines[len(steps)]}' on screen and change it as the line is read.")
    scene.animations = steps


def _shape_opener(scene: SceneBrief) -> None:
    """Hold the first scene to what a title card can actually show.

    The opener is rendered on its own stage — title, one subtitle, an optional
    accent line and the character cast — so a brief that asks it for a hero
    formula with inline callouts sets the reviewer up to fail a scene that is
    behaving exactly as designed. Keep the teaching content; drop the demands the
    layout has nowhere to put.
    """
    scene.scene_type = SceneType.REMOTION
    scene.key_elements = [f"Lesson title: {scene.title}"]
    scene.visual_brief = (
        "Lesson opener on its own stage: the lesson title and one short subtitle "
        "surfacing in the middle of the frame, with the character cast leaning in "
        "from the two bottom corners. No teaching board, no diagram, no bullets."
    )
