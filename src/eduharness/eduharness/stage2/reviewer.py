"""Independent VLM reviewer.

One structured vision call per scene. The verdict is grounded twice:
1. `key_elements` from the blueprint — each must be visibly present.
2. Deterministic guard findings (Manim layout guard, DOM overflow, blank
   frames) are passed in as evidence and, when they are blockers, they fail
   the scene even if the VLM is lenient.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from ..providers.base import Provider
from ..schema import (
    GuardFinding,
    GuardReport,
    RepairOp,
    SceneBrief,
    SceneRepair,
    SceneType,
    StyleConfig,
    layout_contract,
    scene_layout_text,
)
from .media import Frame

SYSTEM = """\
You are an independent visual QA auditor for teaching media. You did not write
the code that produced these frames; judge only what a student would see.

Grade the scene against (a) the VISUAL BRIEF, (b) the KEY ELEMENTS list and
(c) the STYLE CONFIG. Be strict about readability and about whether the scene
actually shows what it was supposed to teach.

BLOCKING issues (the scene fails):
- Text cut off at the frame edge, or two texts/formulas overlapping so either is hard to read
- A label crossing/covering a curve, coordinate axis, arrow shaft/tip, or its
  object's important feature; labels must occupy clear space immediately beside
  their object or in a compact adjoining annotation column
- Old/duplicate labels left visible after a state changes, or labels that collide
  during motion even if the initial and final frames are clean
- Foreground/background contrast too low to read
- Blank, corrupted, or unrelated content; a "placeholder" scene
- A KEY ELEMENT that is not visible at all (list it in missing_key_elements)
- Interactive preview empty, broken, or without the promised controls
- A formula/number that is wrong or contradicts the brief

MINOR issues (nits; never fail a scene for these alone):
- Palette/font drift, slightly cramped spacing, small alignment differences
- Stylistic wishes that were not in the key elements
- An element that IS visible but in a different position/size/style than the brief
  asked for (e.g. "on the right" but it is on the left), provided it stays readable
  and its association with its object is clear. Position alone is never a reason
  to mark a key element missing. Do not classify actual collisions or unreadable
  annotations as minor spacing/style preferences.

Image scenes are complete concept illustrations with their own short labels,
cream/light backgrounds and a restrained teal/gold palette. They do not require
a lecture column, fixed title/footer bands, character, or grid. Older image briefs
may request text-free art or locally composed captions; judge the teaching content
and label readability instead of enforcing those obsolete presentation directions.
For other scene types, check the fixed title and footer bands, left explanation/controls region,
right visual region, and planned A1-F6 element placements. Report concrete
overlap, occlusion, or out-of-frame violations in layout_issues, with the affected
object and a non-overlapping target anchor/area. Preserve title and lecture
positions while proposing repairs.

Every blocking_issue must be a concrete observation about these frames ("the
label '0.2 m' is cut off at the right edge"), never a restatement of this rubric.
For animation defects give the observed frame/time, the exact visible label
text, and the curve/axis/arrow/other label it collides with. Check all supplied
transition and final frames for labels left from the previous state; do not
infer an unseen collision from a motion plan alone. Do not count a curve crossing
an axis, a marker sitting on a curve, or a clear leader line as a text collision.

An interactive screenshot shows the INITIAL state before the student acts:
feedback text, explanations, "Correct!" banners and Continue buttons appear only
after an answer, so never mark them missing — judge the prompt, the controls and
the readability of what is shown.

Scores: score = overall readability + polish (0-10); brief_adherence = how much
of the brief's intent is actually on screen (0-10). A scene with any blocking
issue must score <= 5.

When the scene fails, propose the smallest repair:
- fix_action: patch_artifact when PRIOR ARTIFACT is provided and you can locate
  exact text/fields to change; otherwise re_render; change_tool only when this
  tool fundamentally cannot show the brief.
- ops: minimal precise edits (max 5). Each op has target, op (replace|set|
  append_constraint), before (exact unique substring of PRIOR ARTIFACT for
  replace), after/value.
- fallback_instructions: concrete prose instructions for the executor.

Also return `layout_issues` for spatial problems (overlap, occlusion, off-screen,
bad grid placement) and `temporal_issues` for defects during a transition or left
in a later state (duplicate objects, stale labels, abrupt state changes). Each
item must give the observed defect before its concrete correction; do not repeat
the rubric. Repeat material collisions, unreadable text, and stale annotations
in blocking_issues. A suggested position/style improvement without an observed
defect remains minor.

Allowed targets by scene_type:
- manim: an object name from the PLACEMENT TABLE (set, value = {"area": ["C2", "D4"]}
  for a region or {"cell": "B2"} for a point, optional "scale"), or construct_body
  (replace with unique before/after). Use a placement op when moving a whole
  object/group resolves the defect. When a label collides with a curve or sibling
  label INSIDE that group, moving the whole group preserves the collision: edit
  construct_body instead, adjusting the individual annotate call, direction,
  spacing, or clear adjoining annotation column. The available helper is
  self.annotate(target, text, direction=RIGHT, accent=None, buff=0.18,
                obstacles=(complete_diagram,)). It selects nearby clear space
  after placing the complete diagram and keeps text/leader attached during
  movement. If no clear space fits, reserve a label lane or reduce label text;
  do not shrink all text or move the fixed lecture column. For stale labels,
  replace/update the annotation or remove it with its previous state; reserve
  clear space throughout the movement, not just at the final position.
  Two anchors name opposite corners of a region;
  keep a label within one grid unit of the object it belongs to, and never send
  two objects to overlapping regions in the same verdict.
- remotion: title | subtitle | bullets | bullets[i] | formula | steps | left_items | right_items | accent_label (set/replace)
- image: prompt_addendum (append_constraint)
- interactive: instruction | parameters.<key> (set only; never template)
"""


class _ReviewOut(BaseModel):
    score: float = Field(0.0, ge=0, le=10)
    brief_adherence: float = Field(0.0, ge=0, le=10)
    present_key_elements: list[str] = Field(default_factory=list)
    missing_key_elements: list[str] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)
    minor_issues: list[str] = Field(default_factory=list)
    # Code2Video-style critic fields: describe spatial and temporal defects
    # separately so the repair router can act on concrete layout feedback.
    layout_issues: list[str] = Field(default_factory=list, max_length=8)
    temporal_issues: list[str] = Field(default_factory=list, max_length=8)
    fix_action: str = "re_render"
    ops: list[RepairOp] = Field(default_factory=list)
    fallback_instructions: str = ""


# Guard kinds derived by reading the scene's source rather than by measuring the
# rendered frames. They are held out of the "measured, not guessed" block above,
# because the reviewer trusts that header and repeats whatever it contains as a
# defect of its own -- the same prompt-echo loop that inherited blank-frame
# findings used to cause. See `_grid_layout_findings`.
ADVISORY_GUARD_KINDS = frozenset({"grid_anchor_overlap"})


def _finding_line(finding: GuardFinding) -> str:
    when = f" @ {finding.at_seconds:.1f}s" if finding.at_seconds is not None else ""
    return f"[{finding.severity}] {finding.kind}{when}: {finding.message}"


def _review_error(scene_id: str, scene_type: SceneType | None, message: str) -> SceneRepair:
    return SceneRepair(
        scene_id=scene_id,
        scene_type=scene_type,
        passed=False,
        score=0.0,
        brief_adherence=0.0,
        severity="blocker",
        fix_action="re_render",
        blocking_issues=[message],
        fallback_instructions="",
        review_error=True,
    ).finalize()


def review_scene(
    provider: Provider,
    style: StyleConfig,
    frames: list[Frame],
    *,
    scene: SceneBrief,
    guard: GuardReport | None = None,
    artifact_excerpt: str = "",
    pass_score: float = 7.0,
    visual_seconds: float | None = None,
    narration_seconds: float | None = None,
    opener: bool = False,
) -> SceneRepair:
    guard = guard or GuardReport()
    if scene.scene_type == SceneType.MANIM and artifact_excerpt:
        for finding in _grid_layout_findings(artifact_excerpt):
            if not any(_same_issue(_guard_line(finding), _guard_line(existing)) for existing in guard.findings):
                guard.findings.append(finding)
    if not frames:
        return _review_error(scene.id, scene.scene_type, "No preview frames available")

    frame_lines = []
    for i, f in enumerate(frames, 1):
        tag = f"t={f.seconds:.1f}s"
        if f.label == "guard":
            tag += " (flagged by layout guard)"
        elif f.label == "screenshot":
            tag = "interactive screenshot"
        frame_lines.append(f"Frame {i}: {tag}")
    elements = "\n".join(f"  - {e}" for e in scene.key_elements) or "  (none listed — judge the brief)"
    # The planned steps are what the scene promised to MOVE. A scene that shows
    # every key element but never animates them is a slide, and brief_adherence is
    # where that has to show up.
    animation_plan = "\n".join(f"  {index + 1}. {step}" for index, step in enumerate(scene.animations))
    animation_block = (
        "\nPLANNED ANIMATION STEPS (each should be visible as a change between frames; "
        "count the ones you can actually see in brief_adherence):\n" + animation_plan
        if animation_plan else ""
    )
    measured_lines = [_finding_line(f) for f in guard.findings
                      if f.kind not in ADVISORY_GUARD_KINDS]
    advisory_lines = [_finding_line(f) for f in guard.findings
                      if f.kind in ADVISORY_GUARD_KINDS]
    timing = ""
    if visual_seconds is not None:
        timing = f"\nVISUAL DURATION: {visual_seconds:.1f}s"
        if narration_seconds:
            timing += f" (narration {narration_seconds:.1f}s; the player pads the shorter one)"

    # Judge each scene against the contract it was actually built to. Handing the
    # board contract to the opener made the reviewer ask a title card for a
    # lecture column and a result strip it is designed not to have.
    if opener:
        layout = (
            "Lesson opener on its own stage — deliberately NOT the teaching board: no title "
            "band, no lecture column, no result strip, no anchor grid. Expect the lesson title "
            "and one short subtitle surfacing in the middle of the frame, and a cast of "
            "characters leaning in from the two bottom corners. Judge readability, spelling and "
            "whether the title names this lesson; do not ask for board regions, bullets, "
            "formulas or a takeaway banner."
        )
    elif scene.scene_type == SceneType.INTERACTIVE:
        # The renderer builds these as standalone panels on purpose -- `_render_one`
        # passes an empty teaching_layout. Handing them the board contract asked a
        # practice panel for a title band, a lecture column and a right visual
        # column it is designed not to have, and cost it several points for
        # following its own brief.
        layout = (
            "Standalone practice panel drawn by the interactive runtime - deliberately NOT the "
            "teaching board: no title band, no lecture column, no result strip, no anchor grid, "
            "and no required column. The panel owns the whole frame. Expect the prompt or task, "
            "its controls, and any hint affordance. Judge whether a student can read the prompt "
            "and act on it: legibility, spacing, and whether every control is fully inside the "
            "panel and reachable. Do not ask for board regions, lecture lines or a takeaway "
            "banner, and do not fault the panel for sitting where the template puts it."
        )
    elif scene.scene_type == SceneType.IMAGE:
        layout = (
            "Generated teaching diagram placed in the board's main region: the diagram carries "
            "its own short labels, and the board's title band, lecture column and result strip "
            "are drawn around it by the renderer. Judge the diagram — is the idea legible, are "
            "its labels readable and inside the region — and flag board text only when something "
            "overlaps or is cut off.\n"
            f"{layout_contract(style)}"
        )
    else:
        layout = f"{layout_contract(style)}\nPLANNED ELEMENT PLACEMENTS:\n{scene_layout_text(scene)}"
    prompt = f"""\
SCENE ID: {scene.id}
SCENE TYPE: {scene.scene_type.value}
SCENE TITLE: {scene.title}
NARRATION (what the teacher says over this scene): {scene.narration or "(none)"}
VISUAL BRIEF: {scene.visual_brief}
KEY ELEMENTS (each must be visible):
{elements}{timing}{animation_block}

UNIFIED LAYOUT CONTRACT:
{layout}

STYLE CONFIG:
{style.model_dump_json(indent=2)}

FRAMES ATTACHED ({len(frames)}):
""" + "\n".join(frame_lines) + "\n"
    if measured_lines:
        prompt += (
            "\nDETERMINISTIC LAYOUT GUARD FINDINGS (measured, not guessed; the flagged "
            "frames show them):\n" + "\n".join(f"  - {line}" for line in measured_lines) + "\n"
        )
    if advisory_lines:
        prompt += (
            "\nSTATIC SOURCE HINTS (read off the scene's own grid calls, NOT measured on "
            "these frames). The objects named may never be on screen together — showing one, "
            "fading it, and reusing the area for the next is a deliberate pattern. Treat these "
            "as advisory: mention one only if you can SEE the collision in the frames, and "
            "never make one a blocking issue on its own:\n"
            + "\n".join(f"  - {line}" for line in advisory_lines) + "\n"
        )
    if scene.scene_type == SceneType.MANIM and artifact_excerpt.strip():
        from .repair_apply.manim_ops import position_table

        prompt += (
            "\nPLACEMENT TABLE (the scene's own grid calls — use placement ops to move "
            "whole objects; use construct_body edits for colliding child annotations "
            "or stale labels inside a group):\n" + position_table(artifact_excerpt) + "\n"
        )
    if artifact_excerpt.strip():
        prompt += f"\nPRIOR ARTIFACT (for grounding patch ops):\n{artifact_excerpt.strip()}\n"
    prompt += (
        "\nReturn the structured verdict. List every KEY ELEMENT in exactly one of "
        "present_key_elements / missing_key_elements using its original wording. "
        "For any spatial or transition defect, also include a concise actionable "
        "entry in layout_issues or temporal_issues."
    )

    last_error: Exception | None = None
    for _ in range(2):
        try:
            out = provider.vision_json(
                prompt,
                [str(f.path) for f in frames],
                _ReviewOut,
                system=SYSTEM,
                max_tokens=3000,
            )
            return _to_repair(out, scene, guard, pass_score)
        except Exception as exc:
            last_error = exc
    return _review_error(
        scene.id, scene.scene_type, f"Reviewer unavailable or invalid: {last_error}"
    )


def _to_repair(
    out: _ReviewOut, scene: SceneBrief, guard: GuardReport, pass_score: float
) -> SceneRepair:
    known = {e.strip().lower(): e for e in scene.key_elements}
    missing: list[str] = []
    for item in out.missing_key_elements:
        key = item.strip().lower()
        original = known.get(key)
        if original is None:
            # Accept fuzzy matches (the model sometimes paraphrases).
            original = next((v for k, v in known.items() if key in k or k in key), None)
        if original and original not in missing:
            missing.append(original)
    blocking = [i.strip() for i in out.blocking_issues if i.strip() and not _rubric_echo(i)]
    minor = [i.strip() for i in out.minor_issues if i.strip() and not _rubric_echo(i)]
    # Preserve the Code2Video critic split in the repair feedback. Layout and
    # temporal observations are more actionable than an undifferentiated score.
    spatial = [i.strip() for i in [*out.layout_issues, *out.temporal_issues]
               if i.strip() and not _rubric_echo(i)]
    # A lenient model may put a concrete collision only in layout/temporal or
    # even minor_issues. Promote observed defects, not preventive layout advice.
    for issue in [*minor, *spatial]:
        if _observed_visual_defect(issue):
            if not any(_same_issue(issue, existing) for existing in blocking):
                blocking.append(issue)
        elif issue not in minor and issue not in blocking:
            minor.append(issue)
    minor = [issue for issue in minor
             if not any(_same_issue(issue, existing) for existing in blocking)]

    # The prompt asks for an exact partition of key elements. If the model
    # returned a partial partition, fail closed for the omitted elements once it
    # has demonstrated that it understands the field (legacy/offline providers
    # may return neither list, which remains backward compatible).
    if scene.key_elements and (out.present_key_elements or out.missing_key_elements):
        classified = {item.strip().lower() for item in [*out.present_key_elements, *out.missing_key_elements] if item.strip()}
        for element in scene.key_elements:
            key = element.strip().lower()
            if key in classified:
                continue
            fuzzy = next((item for item in classified if item in key or key in item), None)
            if fuzzy is None:
                missing.append(element)
    # Guard blockers are authoritative — the VLM cannot wave them through.
    for finding in guard.findings:
        line = _guard_line(finding)
        # Any measured geometry defect is a hard failure.  A partial text
        # overlap can still be readable in one frame and unreadable in the
        # next, so do not let the VLM score promote it to a pass.
        # Overlap/occlusion findings are measured collisions.  Out-of-frame
        # findings can also describe a near-edge safe-padding warning (major),
        # so retain the declared severity for those unless the guard marked it
        # as an explicit blocker.
        layout_blocker = finding.kind in {"text_overlap", "text_occluded"}
        if finding.severity == "blocker" or layout_blocker:
            if not any(_same_issue(line, b) for b in blocking):
                blocking.append(line)
        elif finding.severity == "major":
            if not any(_same_issue(line, b) for b in blocking + minor):
                minor.append(line)
    action = out.fix_action if out.fix_action in {
        "patch_artifact", "re_render", "change_tool", "adjust_timing", "noop"
    } else "re_render"
    repair = SceneRepair(
        scene_id=scene.id,
        scene_type=scene.scene_type,
        score=out.score,
        brief_adherence=out.brief_adherence,
        blocking_issues=blocking,
        minor_issues=minor,
        missing_key_elements=missing,
        fix_action=action,  # type: ignore[arg-type]
        ops=out.ops[:5],
        fallback_instructions=out.fallback_instructions.strip(),
    )
    return repair.finalize(pass_score=pass_score)


def _observed_visual_defect(issue: str) -> bool:
    """Recognize concrete defects misplaced in a non-blocking review field.

    This supplements the reviewer's explicit blocking list; it is deliberately
    limited to visual defects, so a suggested new position cannot fail a scene.
    """
    clauses = re.split(r"[;\n]|\.(?:\s|$)|\bbut\b", issue.lower())
    for clause in clauses:
        # The reviewer writes the observation first and correction afterwards.
        # Hypothetical/preventive advice is not evidence of a visible defect.
        if re.search(r"\b(?:avoid|prevent|potential|risk|could|might|may)\b", clause):
            continue
        if re.match(r"\s*(?:move|place|reposition|keep|reserve|increase|decrease|consider)\b", clause):
            continue
        defects = re.finditer(
            r"(?<![\w-])(?:overlap(?:s|ping|ped)?|collid(?:e[sd]?|ing)|occlud(?:e[sd]?|ing)|"
            r"obscur(?:e[sd]?|ing)|covered by|cut off|off[- ]screen|"
            r"outside the (?:frame|viewport)|unreadable|illegible|"
            r"duplicate objects?)(?![\w-])", clause,
        )
        for defect in defects:
            prefix = clause[:defect.start()]
            if not re.search(r"\b(?:no|not|never|without)\b(?:\s+[\w'-]+){0,3}\s*$", prefix):
                return True
        if not re.search(r"\b(?:label|annotation|text|formula)s?\b", clause):
            continue
        if re.search(r"\b(?:stale|obsolete|duplicate)\b", clause):
            if not re.search(r"\b(?:no|not|without)\b", clause):
                return True
        if re.search(r"\b(?:old|previous)\b", clause) and re.search(
            r"\b(?:remains?|persists?|lingers?|left visible|still visible)\b", clause
        ) and re.search(r"\b(?:after|new state|state changes|final|replaced)\b", clause):
            return True
        if re.search(
            r"\b(?:label|annotation|text|formula)s?\b.{0,100}"
            r"\b(?:cross(?:es|ing)|intersect(?:s|ing)|cover(?:s|ing))\b", clause
        ) and re.search(
            r"\b(?:curve|axis|axes|arrow)s?\b", clause
        ) and not re.search(r"\b(?:no|not|without)\b", clause):
            return True
    return False


_GRID_POINT = re.compile(r"self\.place_at_grid\(\s*([^,]+),\s*['\"]([A-F][1-6])['\"]")
_GRID_AREA = re.compile(r"self\.place_in_area\(\s*([^,]+),\s*['\"]([A-F][1-6])['\"]\s*,\s*['\"]([A-F][1-6])['\"]")


def _artifact_code(excerpt: str) -> str:
    try:
        value = json.loads(excerpt)
        if isinstance(value, dict) and isinstance(value.get("construct_body"), str):
            return value["construct_body"]
    except (TypeError, ValueError):
        pass
    return excerpt


def _grid_layout_findings(excerpt: str) -> list[GuardFinding]:
    """Detect duplicate Code2Video anchors before the VLM call.

    This is intentionally conservative: it flags only exact point collisions,
    and overlapping declared areas. A visual reviewer still decides whether a
    deliberate shared panel is readable.

    It carries its own `grid_anchor_overlap` kind rather than `text_overlap`,
    because this is a regex over source, not a measurement of the rendered
    frame, and `_to_repair` makes measured overlaps blocking regardless of
    severity. Sharing the kind handed a static guess that same veto — and the
    Manim authoring prompt explicitly teaches sequential reuse of one region
    ("show one, FadeOut its braces and labels, then show the next in the same
    place"), which this scan, having no notion of time, reads as a collision.
    """
    code = _artifact_code(excerpt)
    occupied: list[tuple[str, set[tuple[int, int]]]] = []
    for match in _GRID_POINT.finditer(code):
        cell = match.group(2)
        occupied.append((match.group(1).strip(), {(ord(cell[0]) - 65, int(cell[1]) - 1)}))
    for match in _GRID_AREA.finditer(code):
        a, b = match.group(2), match.group(3)
        cells = {(col, row) for col in range(ord(a[0]) - 65, ord(b[0]) - 64)
                 for row in range(int(a[1]) - 1, int(b[1]))}
        occupied.append((match.group(1).strip(), cells))
    findings: list[GuardFinding] = []
    for i, (left_name, left_cells) in enumerate(occupied):
        for right_name, right_cells in occupied[i + 1:]:
            shared = left_cells & right_cells
            if shared and left_name != right_name:
                cells = ", ".join(f"{chr(c + 65)}{r + 1}" for c, r in sorted(shared))
                findings.append(GuardFinding(
                    kind="grid_anchor_overlap", severity="major",
                    message=f"Code2Video grid anchors for {left_name} and {right_name} share {cells}; move one object to a free cell",
                    subjects=[left_name, right_name],
                ))
    return findings[:8]


_RUBRIC_PHRASES = (
    "list it in missing_key_elements",
    "a key element that is not visible",
    "blocking issues (the scene fails)",
)


def _rubric_echo(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in _RUBRIC_PHRASES)


def _guard_line(finding: GuardFinding) -> str:
    when = f" at {finding.at_seconds:.1f}s" if finding.at_seconds is not None else ""
    return f"[layout guard] {finding.message}{when}"


def _same_issue(a: str, b: str) -> bool:
    x = a.lower().replace("[layout guard] ", "")
    y = b.lower().replace("[layout guard] ", "")
    return x == y or x in y or y in x


# --------------------------------------------------------------------------- screenshots
def _launch_chromium(playwright):
    """Chromium for the interactive preview, falling back to the render toolchain's.

    Playwright's own download is missing its shared libraries on some hosts, and a
    failure here costs a scene its review entirely ("No preview frames available"),
    so retry with the Chrome that Remotion already renders through — including the
    project-local NSS/NSPR libraries it needs.
    """
    args = ["--no-sandbox", "--autoplay-policy=no-user-gesture-required"]
    try:
        return playwright.chromium.launch(args=args)
    except Exception:
        from .adapters.remotion import _browser_env, browser_executable, template_root

        template = template_root()
        executable = browser_executable(template)
        if not executable:
            raise
        return playwright.chromium.launch(executable_path=executable, env=_browser_env(template),
                                          args=args)


def screenshot_html(
    html_path: Path,
    out_png: Path,
    *,
    width: int = 1920,
    height: int = 1080,
) -> tuple[Optional[Path], list[GuardFinding]]:
    """Playwright screenshot of the trusted interactive runtime + DOM overflow audit."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, [GuardFinding(kind="missing_asset", severity="blocker",
                                   message="playwright not installed; interactive preview unavailable")]
    out_png.parent.mkdir(parents=True, exist_ok=True)
    findings: list[GuardFinding] = []
    try:
        with sync_playwright() as p:
            browser = _launch_chromium(p)
            page = browser.new_page(viewport={"width": width, "height": height})
            errors: list[str] = []
            page.on("pageerror", lambda err: errors.append(str(err)))
            page.goto(html_path.resolve().as_uri(), wait_until="networkidle")
            page.wait_for_timeout(250)
            audit = page.evaluate(
                """() => {
                  const vw = window.innerWidth, vh = window.innerHeight;
                  const out = [];
                  const root = document.getElementById('interactive');
                  if (!root || !root.children.length) return {empty: true, overflow: out};
                  for (const el of root.querySelectorAll('*')) {
                    const r = el.getBoundingClientRect();
                    if (r.width === 0 || r.height === 0) continue;
                    if (r.right > vw + 1 || r.bottom > vh + 1 || r.left < -1 || r.top < -1) {
                      out.push((el.tagName.toLowerCase()) + (el.className ? '.' + String(el.className).split(' ')[0] : '')
                        + ' [' + Math.round(r.left) + ',' + Math.round(r.top) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height) + ']');
                      if (out.length >= 6) break;
                    }
                  }
                  return {empty: false, overflow: out, scrollH: document.documentElement.scrollHeight, vh};
                }"""
            )
            page.screenshot(path=str(out_png), full_page=False)
            browser.close()
        if errors:
            findings.append(GuardFinding(kind="dom_overflow", severity="blocker",
                                         message=f"runtime JS error: {errors[0][:200]}"))
        if audit.get("empty"):
            findings.append(GuardFinding(kind="dom_overflow", severity="blocker",
                                         message="interactive root rendered no elements"))
        for item in audit.get("overflow", []):
            findings.append(GuardFinding(kind="dom_overflow", severity="major",
                                         message=f"element outside the viewport: {item}"))
        return (out_png if out_png.is_file() else None), findings
    except Exception as exc:
        log = out_png.with_suffix(".screenshot_error.txt")
        try:
            log.write_text(f"{html_path}\n{type(exc).__name__}: {exc}\n", encoding="utf-8")
        except OSError:
            pass
        return None, [GuardFinding(kind="missing_asset", severity="blocker",
                                   message=f"screenshot failed: {type(exc).__name__}: {exc}"[:300])]


# --------------------------------------------------------------------------- legacy shims
def review_frames(
    provider: Provider,
    style: StyleConfig,
    image_paths: list[Path],
    *,
    scene_title: str,
    visual_brief: str,
    scene_id: str = "",
    scene_type: SceneType | None = None,
    artifact_excerpt: str = "",
) -> SceneRepair:
    """Backward-compatible wrapper around review_scene for plain image lists."""
    scene = SceneBrief(
        id=scene_id or "scene", title=scene_title,
        scene_type=scene_type or SceneType.IMAGE, visual_brief=visual_brief,
    )
    frames = [Frame(path=Path(p), seconds=0.0, label="uniform") for p in image_paths]
    return review_scene(provider, style, frames, scene=scene, artifact_excerpt=artifact_excerpt)


def dump_review(path: Path, repair: SceneRepair, frames: list[Frame], guard: GuardReport) -> None:
    payload = repair.model_dump()
    payload["frames"] = [{"path": str(f.path), "seconds": f.seconds, "label": f.label} for f in frames]
    payload["guard"] = guard.model_dump()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
