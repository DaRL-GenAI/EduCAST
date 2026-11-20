"""Generate a detailed English flowchart of the education_video / EduHarness method."""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

# ---------------------------------------------------------------- palette
GROUND   = "#FAFBF8"
INK      = "#17201B"
PRIMARY  = "#356B8F"   # API / model call
SECOND   = "#16734A"   # local / offline / deterministic
DANGER   = "#B4423D"   # gate, failure, human hand-off
MUTED    = "#6E7A72"
PANEL    = "#FFFFFF"
SANS = "IBM Plex Sans, Inter, Helvetica Neue, Arial, sans-serif"
MONO = "IBM Plex Mono, SF Mono, Menlo, Consolas, monospace"

TITLE_S, BODY_S, KICK_S = 15.5, 12.0, 10.0
LH = 16.2

out: list[str] = []


def esc(t: str) -> str:
    return escape(str(t))


def wrap(text: str, width_px: float, size: float = BODY_S, mono: bool = False) -> list[str]:
    per = size * (0.605 if mono else 0.523)
    limit = max(8, int(width_px / per))
    words, lines, cur = text.split(" "), [], ""
    for w in words:
        cand = w if not cur else cur + " " + w
        if len(cand) <= limit:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            while len(w) > limit:
                lines.append(w[: limit - 1] + "-")
                w = w[limit - 1 :]
            cur = w
    if cur:
        lines.append(cur)
    return lines


def text_el(x, y, t, size=BODY_S, fill=INK, opacity=1.0, weight=400, font=SANS, ls=0, anchor="start"):
    out.append(
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="{font}" font-size="{size}" '
        f'fill="{fill}" fill-opacity="{opacity}" font-weight="{weight}" '
        f'letter-spacing="{ls}" text-anchor="{anchor}">{esc(t)}</text>'
    )


def box_height(lines: list[str], w: float, title: str | None, kicker: str | None,
               pad=13.0, body_size=BODY_S, mono=False) -> float:
    h = pad
    if kicker:
        h += 13
    if title:
        h += 20
    n = 0
    for ln in lines:
        n += len(wrap(ln.lstrip("• "), w - 2 * pad - (9 if ln.startswith("• ") else 0), body_size, mono))
    h += n * (LH if body_size >= 11.5 else body_size * 1.36)
    return h + pad - 2


def box(x, y, w, lines, *, title=None, kicker=None, accent=INK, fill=PANEL,
        dashed=False, pad=13.0, body_size=BODY_S, body_opacity=0.80, lw=1.25,
        body_font=SANS) -> float:
    h = box_height(lines, w, title, kicker, pad, body_size, body_font == MONO)
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    out.append(
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="3" '
        f'fill="{fill}" stroke="{accent}" stroke-width="{lw}"{dash}/>'
    )
    out.append(
        f'<rect x="{x:.1f}" y="{y:.1f}" width="3.2" height="{h:.1f}" fill="{accent}" opacity="0.9"/>'
    )
    cy = y + pad + 1
    if kicker:
        cy += 8
        text_el(x + pad, cy, kicker, KICK_S, accent, 0.85, 600, MONO, 0.09)
        cy += 5
    if title:
        cy += 15
        text_el(x + pad, cy, title, TITLE_S, INK, 1.0, 600)
        cy += 5
    step = LH if body_size >= 11.5 else body_size * 1.36
    for ln in lines:
        bullet = ln.startswith("• ")
        body = ln.lstrip("• ")
        ind = 9 if bullet else 0
        for i, seg in enumerate(wrap(body, w - 2 * pad - ind, body_size, body_font == MONO)):
            cy += step
            if bullet and i == 0:
                out.append(
                    f'<circle cx="{x + pad + 2.4:.1f}" cy="{cy - 4:.1f}" r="1.9" fill="{accent}" opacity="0.75"/>'
                )
            text_el(x + pad + ind, cy, seg, body_size, INK, body_opacity, font=body_font)
    return h


def arrow(x1, y1, x2, y2, label="", color=INK, dashed=False, label_dx=8, label_dy=-5,
          label_anchor="start", width=1.4, op=1.0):
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    marker = "ahR" if color == DANGER else ("ahG" if color == SECOND else ("ahB" if color == PRIMARY else "ah"))
    out.append(
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" '
        f'stroke-opacity="{op}" stroke-width="{width}"{dash} marker-end="url(#{marker})"/>'
    )
    if label:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        text_el(mx + label_dx, my + label_dy, label, 10.6, color, 0.95, 600, MONO, 0.04, label_anchor)


def path_arrow(d, label="", color=INK, dashed=False, lx=0, ly=0, anchor="start", width=1.4):
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    marker = "ahR" if color == DANGER else ("ahG" if color == SECOND else ("ahB" if color == PRIMARY else "ah"))
    out.append(
        f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}"{dash} '
        f'marker-end="url(#{marker})"/>'
    )
    if label:
        text_el(lx, ly, label, 10.6, color, 0.95, 600, MONO, 0.04, anchor)


def artifact(x, y, w, label, sub="", accent=SECOND) -> float:
    h = 40.0 if not sub else 54.0
    out.append(
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="19" '
        f'fill="{GROUND}" stroke="{accent}" stroke-width="1.2" stroke-dasharray="3 3"/>'
    )
    text_el(x + w / 2, y + (24 if sub else 25), label, 12.2, accent, 1.0, 600, MONO, 0.03, "middle")
    if sub:
        text_el(x + w / 2, y + 42, sub, 11.2, INK, 0.7, 400, SANS, 0, "middle")
    return h


# ---------------------------------------------------------------- geometry
W = 1760
ML, MW = 40, 1180          # main column
RL, RW = 1256, 464         # right rail
CX = ML + MW / 2

y = 126

# ------------------------------------------------------------- 0. request
h = box(ML, y, MW, [
    "• topic · audience · learning_goal · source_text (notes, transcript or outline) · language",
    "• preferred_theme · voice · parallel (4) · max_review_rounds (1-6) · allow_unreviewed_bundle",
    "• enable_manim / enable_remotion / enable_image / enable_narration — feature flags the planner must respect",
], title="Structured request  —  examples/*.json validated into HarnessRequest",
   kicker="INPUT", accent=INK)
req_bottom = y + h
y += h + 26

# ------------------------------------------------------------- 1. stage 1
s1_top = y
arrow(CX, req_bottom, CX, s1_top, "plan", PRIMARY, label_dx=10)

h1 = box(ML, y, MW, [
    "One structured-output call with reasoning_effort=high. The model plans CONTENT ONLY: it never invents "
    "palettes, coordinates, ratios or card chrome — the host pins those after planning, so media and player "
    "chrome can never drift apart.",
], title="Stage 1 — Main Agent (planner)", kicker="LLM · gpt-5 / gpt-5.6-sol", accent=PRIMARY)
y += h1 + 14

col_w = (MW - 2 * 14) / 3
c1 = box(ML, y, col_w, [
    "• 5-8 scenes, 15-40 s of narration each",
    "• each routed to exactly ONE tool: image / manim / remotion / interactive",
    "• at least one interactive scene after the core concept is taught (ICAP)",
    "• at most 3 key_scene:true — those get 5 lecture_lines + 5 animations, the rest 3 + 3",
], title="Lesson split", kicker="SCENES", accent=PRIMARY)
c2 = box(ML + col_w + 14, y, col_w, [
    "• visual_brief: what is drawn, where, in which palette role, in what order",
    "• key_elements: 2-5 short checkable statements of what MUST be visible",
    "• animations: one step per lecture line, naming what MOVES (not what exists)",
    "• narration 2-4 sentences + target_seconds (about 2.6 words/second)",
    "• trigger_scene_id / trigger_at_seconds to interrupt a video with practice",
], title="Per-scene contract", kicker="BRIEF", accent=PRIMARY)
c3 = box(ML + 2 * (col_w + 14), y, col_w, [
    "• planner names a theme; schema._sanitize pins the exact values from THEMES",
    "• studio_light (default) / academic_dark — ground, ink, primary, secondary, danger",
    "• one fixed teaching board: title band, left lecture column, right visual column, A1-F6 anchor grid, result strip",
    "• three exceptions: title card, image scene, interactive panel",
], title="Host pins the style", kicker="BOARD", accent=SECOND)
y += max(c1, c2, c3) + 18

ha = artifact(ML + MW * 0.14, y, MW * 0.72,
              "blueprint/lesson_blueprint.json  +  blueprint/style_config.json",
              "the only contract between planning and rendering")
y += ha + 26

# ------------------------------------------------------------- 2. stage 2
s2_top = y
arrow(CX, s2_top - 26, CX, s2_top + 34, "", INK)
inner_l = ML + 26
inner_w = MW - 52
y = s2_top + 44

hh = box(inner_l, y, inner_w, [
    "workflow.run_repair_loop — prepare -> render -> review, re-doing ONLY the scenes that still fail, "
    "up to max_review_rounds. Scenes run concurrently (ThreadPool, EDUHARNESS_PARALLEL). Every pass is "
    "idempotent and checkpointed, so a crashed or disconnected run resumes instead of restarting.",
], title="Stage 2 — Executor + deterministic guards + independent VLM reviewer",
   kicker="THREE IDEMPOTENT PASSES", accent=INK, fill=GROUND)
y += hh + 20
loop_top = y

# ---- prepare
hp = box(inner_l, y, inner_w, [
    "• narration: one TTS call per scene (gpt-4o-mini-tts), cached by SHA of the text, measured into seconds "
    "that later drive the scene's duration",
    "• the router reuses a prior artifact whenever the scene did not fail, so a passed scene is never re-billed",
], title="PREPARE  —  everything that needs the API", kicker="PASS 1 · NEEDS KEY", accent=PRIMARY)
prep_top = y
y += hp + 14
arrow(CX, y - 14, CX, y - 2, "", INK, op=0.55, width=1.2)

aw = (inner_w - 3 * 12) / 4
a1 = box(inner_l, y, aw, [
    "gpt-4o expands brief + audience + narration + key_elements into one detailed English prompt "
    "(saved as image_prompt.txt), then gpt-image-2 draws a 1536x1024 labelled teaching diagram at high quality.",
], title="image", kicker="ADAPTER", accent=PRIMARY, body_size=11.2, pad=11)
a2 = box(inner_l + aw + 12, y, aw, [
    "The model emits a construct() BODY only. AST validation + normalize_tex_escapes (models "
    "double-escape raw strings, so MathTex(r\"\\\\tau\") becomes a line break plus the word tau) -> manim_spec.json.",
], title="manim", kicker="ADAPTER", accent=PRIMARY, body_size=11.2, pad=11)
a3 = box(inner_l + 2 * (aw + 12), y, aw, [
    "One beat spec chosen from the pinned template: title_card | bullets | formula | compare | steps | "
    "recap | stat_row -> remotion_spec.json.",
], title="remotion", kicker="ADAPTER", accent=PRIMARY, body_size=11.2, pad=11)
a4 = box(inner_l + 3 * (aw + 12), y, aw, [
    "JSON parameters for physics_lever | multiple_choice | drag_sort | fill_blank | number_line, validated by "
    "the Pydantic template registry; invalid values are replaced by template defaults and recorded as a warning.",
], title="interactive", kicker="ADAPTER", accent=PRIMARY, body_size=11.2, pad=11)
y += max(a1, a2, a3, a4) + 16
arrow(CX, y - 16, CX, y - 2, "", INK, op=0.55, width=1.2)

hart = artifact(inner_l + inner_w * 0.16, y, inner_w * 0.68, "prepared_scenes.json",
                "spec paths · narration path + seconds · attempt · prepare fingerprint", SECOND)
y += hart + 20
arrow(CX, y - 20, CX, y - 2, "", INK, op=0.55, width=1.2)

# ---- render
hr = box(inner_l, y, inner_w, [
    "• manim: assemble_script = theme header + guard-safe scene kit (title_bar, card, chip, callout, "
    "self.annotate, row/column/place, bar_chart, reveal/emphasize/swap) + _EduGuardScene, run in a restricted "
    "subprocess — whitelisted env, RLIMIT cpu/fsize/nofile, optionally docker run --network none",
    "• remotion: pinned Remotion 4.0.200 project rendered through a Chrome build checked for completeness "
    "(a headless shell without icudtl.dat answers --version and then dies, silently turning every scene into a slide); "
    "on failure a Pillow/ffmpeg slide fallback is rendered and flagged",
    "• image: compose_concept_image places the art in the board's main region — aspect-contained, never "
    "cover-cropped, ground blended, snap_art=False because quantizing shreds the small labels; isolated art "
    "instead goes through snap_to_board()",
    "• interactive: interactive/<id>.json + a preview HTML for the trusted zero-dependency runtime",
    "• finish: narration muxed in (the shorter track is padded), ensure_web_playable re-encodes to H.264 + faststart",
    "• no LaTeX toolchain? _latex_to_plain rewrites formulas to Unicode AT RENDER TIME ONLY — the downgrade is "
    "never written back into the spec, so a later re-render on a TeX host recovers the real formulas",
], title="RENDER  —  local, offline, no API key required", kicker="PASS 2 · OFFLINE", accent=SECOND)
rend_top = y
y += hr + 14
arrow(CX, y - 14, CX, y - 2, "", INK, op=0.55, width=1.2)

gw = (inner_w - 12) / 2
g1 = box(inner_l, y, gw, [
    "Measures text bounding boxes after every play()/wait() and samples motion at 0.25 s intervals. "
    "guard.json records text out of frame, text/text collisions, and text intersecting sampled Bezier strokes, "
    "filled geometry, axes or arrow shafts. It MEASURES, it never moves labels. Flagged timestamps become extra "
    "review frames; guard blockers fail the scene even if the VLM is lenient.",
], title="Deterministic layout guard", kicker="MEASURED, NOT GUESSED", accent=SECOND, body_size=11.4, pad=11)
g2 = box(inner_l + gw + 12, y, gw, [
    "A blocker/major text_overlap, text_out_of_frame or text_occluded triggers ONE regeneration driven by the "
    "guard lines — acting on a measurement needs no visual review. The two renders are compared by defect score; "
    "the loser is rolled back completely, spec and mp4 together, so the checkpoint always describes the file on disk.",
], title="Guard retry (manim, once)", kicker="CHEAP SECOND ATTEMPT", accent=SECOND, body_size=11.4, pad=11)
y += max(g1, g2) + 16
arrow(CX, y - 16, CX, y - 2, "", INK, op=0.55, width=1.2)

hart2 = artifact(inner_l + inner_w * 0.16, y, inner_w * 0.68, "rendered_scenes.json",
                 "media path · render_mode · guard report · durations · render fingerprint", SECOND)
y += hart2 + 20
arrow(CX, y - 20, CX, y - 2, "", INK, op=0.55, width=1.2)

# ---- review
hv = box(inner_l, y, inner_w, [
    "• frames: 5 uniform samples per video PLUS every guard-flagged timestamp; interactive scenes are "
    "screenshotted with Playwright; payload size tuned by FRAMES_PER_VIDEO / FRAME_WIDTH / VISION_DETAIL",
    "• review-time guards, recomputed on every pass so a fixed defect cannot haunt the next round: blank_frame, "
    "dom_overflow, missing_asset, grid_anchor_overlap (advisory — mention only if visible in the frames)",
    "• ONE structured verdict per scene: score, brief_adherence, an exact partition of key_elements into "
    "present/missing, blocking_issues, minor_issues, layout_issues, temporal_issues, fix_action, ops (<=5), "
    "fallback_instructions",
], title="REVIEW  —  independent VLM auditor over frames + guard evidence",
   kicker="PASS 3 · NEEDS KEY", accent=PRIMARY)
rev_top = y
y += hv + 14
arrow(CX, y - 14, CX, y - 2, "", INK, op=0.55, width=1.2)

hhard = box(inner_l, y, inner_w, [
    "• a concrete defect parked in minor/layout/temporal is promoted to blocking; a key element the model failed "
    "to classify fails closed; rubric echoes are dropped",
    "• guard blockers are authoritative — the VLM cannot wave a measured collision through",
    "• PASS = zero blocking issues AND score >= EDUHARNESS_PASS_SCORE (7). Minor nits never burn a repair round",
    "• a reviewer outage is retried twice, then recorded as review_error -> debug/<id>_HITL.txt. An unauditable "
    "scene is never regenerated and never passed",
], title="Why a lenient reviewer still cannot pass a broken scene",
   kicker="HARDENING", accent=DANGER)
y += hhard + 18
arrow(CX, y - 18, CX, y - 2, "", INK, op=0.55, width=1.2)

# ---- decision
dw, dh = 250.0, 54.0
dx = inner_l + (inner_w - dw) / 2
out.append(
    f'<path d="M {dx+18} {y} L {dx+dw-18} {y} L {dx+dw} {y+dh/2} L {dx+dw-18} {y+dh} '
    f'L {dx+18} {y+dh} L {dx} {y+dh/2} Z" fill="{GROUND}" stroke="{DANGER}" stroke-width="1.5"/>'
)
text_el(dx + dw / 2, y + dh / 2 - 3, "scene passed?", 14, INK, 1.0, 600, SANS, 0, "middle")
text_el(dx + dw / 2, y + dh / 2 + 13, "0 blocking  &  score >= 7", 10.4, DANGER, 0.95, 600, MONO, 0.03, "middle")
dec_y, dec_mid = y, y + dh / 2
y += dh + 22

# pass branch -> right
pill_x, pill_w = dx + dw + 62, inner_l + inner_w - (dx + dw + 62)
path_arrow(f"M {dx+dw} {dec_mid} L {pill_x-6} {dec_mid}", "PASS", SECOND,
           lx=dx + dw + 14, ly=dec_mid - 8)
out.append(f'<rect x="{pill_x:.1f}" y="{dec_mid-26:.1f}" width="{pill_w:.1f}" height="52" rx="4" '
           f'fill="{PANEL}" stroke="{SECOND}" stroke-width="1.3"/>')
out.append(f'<rect x="{pill_x:.1f}" y="{dec_mid-26:.1f}" width="3.2" height="52" fill="{SECOND}"/>')
text_el(pill_x + 12, dec_mid - 8, "Scene frozen", 13.6, INK, 1.0, 600)
text_el(pill_x + 12, dec_mid + 8, "fingerprints keep it current: it is never re-prepared,", 11.0, INK, 0.78)
text_el(pill_x + 12, dec_mid + 21, "never re-rendered and never billed again", 11.0, INK, 0.78)

# ---- repair router
hrep = box(inner_l, y, inner_w, [
    "• fix_action=patch_artifact with grounded ops -> applied LOCALLY to the prior artifact "
    "(manim_ops / remotion_ops / interactive_ops / image_ops). No model call, no drift.",
    "• patch once per artifact: if the patched scene fails again the defect is structural, so the next round "
    "regenerates from prior artifact + feedback + guard findings (Remotion may switch beat)",
    "• exception — pure placement ops on manim keep the patch route: moving an object cannot break what the "
    "scene draws, and layout usually settles over two passes because the second collision only becomes visible "
    "once the first is gone",
    "• fix_action=change_tool rewrites the scene's tool in the blueprint; adjust_timing retimes it",
    "• attempt >= max_review_rounds - 1 -> budget exhausted: checkpoints are left untouched and the scene is "
    "written to debug/<id>_HITL.txt for a human",
], title="Repair router  —  diff first, regenerate only when the diff failed",
   kicker="FAIL", accent=DANGER)
rep_top = y
y += hrep + 8
rep_bottom = y

arrow(dx + dw / 2, dec_y + dh, dx + dw / 2, rep_top, "FAIL", DANGER, label_dx=10)

# loop back arrow on the left
lx = inner_l - 14
path_arrow(
    f"M {inner_l} {rep_top + 30} L {lx} {rep_top + 30} L {lx} {prep_top + 24} L {inner_l - 2} {prep_top + 24}",
    "", DANGER)
_mid = (prep_top + rep_top) / 2
out.append(
    f'<text transform="translate({lx-7:.1f},{_mid:.1f}) rotate(-90)" font-family="{MONO}" font-size="10.8" '
    f'fill="{DANGER}" font-weight="600" letter-spacing="0.04" text-anchor="middle">'
    f'repairs_by_id — only the failed scene ids re-enter the loop</text>')

# stage-2 container
s2_h = y - s2_top + 4
out.append(
    f'<rect x="{ML+6}" y="{s2_top+16}" width="{MW-12}" height="{s2_h}" rx="4" fill="none" '
    f'stroke="{INK}" stroke-opacity="0.32" stroke-width="1.2" stroke-dasharray="6 5"/>'
)
text_el(ML + 22, s2_top + 36, "STAGE 2", KICK_S + 0.6, INK, 0.6, 600, MONO, 0.1)
s2_bottom = s2_top + 16 + s2_h
y = s2_bottom + 62


# ------------------------------------------------------------- 3. stage 3
s3_top = y
arrow(CX, s2_bottom + 14, CX, s3_top - 4, "", SECOND)
text_el(CX + 14, s2_bottom + 40, "every scene passed  (or allow_unreviewed_bundle)",
        10.8, SECOND, 0.95, 600, MONO, 0.04)
h3 = box(ML, y, MW, [
    "• strict quality gate first: every scene's media, timeline position and review state are validated BEFORE "
    "an already published bundle is touched; allow_unreviewed_bundle downgrades the stop to bundle/warnings.json",
    "• timeline: video and image items advance the cursor; an interactive node pauses the stream and adds no "
    "duration; a scene carrying trigger_scene_id becomes an overlay fired inside its parent video at trigger_at",
    "• bundle/: manifest.json (+ content_version hash), media/, interactive/, index.html, player.js, ffmpeg posters",
    "• player: narration with captions, chapter navigation, resume state, interactive checkpoints, ?layout=board",
], title="Stage 3 — EduBundle + hybrid video / interactive player", kicker="OFFLINE", accent=SECOND)
y += h3 + 16
h3a = artifact(ML + MW * 0.14, y, MW * 0.72, "runs/<id>/bundle/  —  a self-contained non-linear lesson",
               "manifest.json + media + interactive JSON + player", SECOND)
y += h3a + 26

# ------------------------------------------------------------- 4. delivery
arrow(CX, y - 26, CX, y, "", INK)
hd = box(ML, y, MW, [
    "• python -m eduharness.serve runs/<id>/bundle — range-capable local preview; python -m eduharness.preview "
    "runs/<id> — ONE self-contained HTML with every asset inlined",
    "• Render Studio (:8080) scans every run checkpoint, shows the active renderer and review state, and starts "
    "the CLI as a background job (.studio/job.json, .studio/job.log) — the browser never owns the generation process",
    "• Public showcase (:8091) + cloudflared quick tunnel: read-only homepage and featured bundles, no creation "
    "controls, no logs, no job endpoints",
], title="Delivery, recovery and publication", kicker="OUTPUT", accent=INK)
y += hd + 30

main_bottom = y

# ------------------------------------------------------------- right rail
ry = 126
rail_boxes = [
    (["• TEXT + VISION (planner, executors, reviewer) -> a company relay: EDUHARNESS_TEXT_BASE_URL / _API_KEY / "
      "_MODEL. Relays that enforce strict JSON schemas fall back to json_object with the schema in the system "
      "prompt; 502/503/504 are retried.",
      "• IMAGE + TTS -> the official API: EDUHARNESS_MEDIA_*. Without it, image scenes and narration are simply "
      "disabled rather than faked.",
      "• A relay can pass generation and still fail review: the audit sends several frames plus a long prompt in "
      "one call, and a short upstream timeout cuts it off. Shrink the payload or split the endpoint — the pipeline "
      "never passes a scene it could not audit."],
     "Two endpoints, one pipeline", "PROVIDER SPLIT", PRIMARY),

    (["runs/<id>/",
      "\u00a0\u00a0blueprint/ — lesson_blueprint.json, style_config.json",
      "\u00a0\u00a0prepared_scenes.json — API checkpoints",
      "\u00a0\u00a0rendered_scenes.json — local output + guard + verdict",
      "\u00a0\u00a0work/<scene>/ — specs, <scene>.py, guard.json,",
      "\u00a0\u00a0\u00a0\u00a0narration.mp3, render logs",
      "\u00a0\u00a0media/ · interactive/ · frames/",
      "\u00a0\u00a0debug/<scene>_review_r<n>.json — verdict, frames, evidence",
      "\u00a0\u00a0debug/<scene>_HITL.txt — needs a human",
      "\u00a0\u00a0bundle/ · usage.json · result.json"],
     "Run directory — the whole state is on disk", "CHECKPOINTS", SECOND),

    (["• prepare_fingerprint and render_fingerprint hash the scene brief, the style, the spec and the adapter "
      "MODULE DIGEST, so editing an adapter marks its outputs stale automatically",
      "• --stage 2 resumes: passed scenes are kept, failed ones re-enter within their budget",
      "• --force drops stored verdicts instead of reusing them, because a verdict describes the look it audited"],
     "Idempotence and resume", "WHY IT CONVERGES", SECOND),

    (["Run stage 1 and 2-prepare where the API is reachable (Colab) -> sync the run directory -> run 2-render "
      "locally with no key -> sync back -> 2-review -> repeat until every scene passes -> 3 locally, then preview. "
      "The same CLI drives both halves; notebooks/ holds the Colab runners."],
     "Hybrid Colab / local workflow", "SPLIT EXECUTION", INK),

    (["• usage.json is a per-call ledger: tokens, images, TTS characters, USD",
      "• measured cost is roughly $2.5-6.7 per lesson; Stage 1 alone takes about 10 minutes",
      "• api_usage_tracker.py prices the notebook-driven runs the same way"],
     "Cost and time ledger", "ACCOUNTING", PRIMARY),

    (["• scripts/setup_env.sh keeps the venv, Chrome and extracted -dev headers on EDUHARNESS_STORE (a mounted "
      "volume) and only re-links ffmpeg into /usr/local/bin, because anything under /usr is wiped when the host "
      "image is reset",
      "• it exists to prevent two failures that LOOK like a working run: a Chrome torso with no icudtl.dat beside "
      "it, and a global LD_LIBRARY_PATH that hands conda's libicu to Chrome"],
     "Persistent toolchain on a resettable host", "ENVIRONMENT", DANGER),

    (["• baseline runners drive Code2Video, plain Manim, plain Remotion and TeachingMonster over the same "
      "topics.xlsx topic set, from Colab notebooks",
      "• the teachgen evaluator scores any final video: per-chunk extractors (content / visual-multimedia / "
      "pedagogy) -> section and lecture inference -> three rubric graders -> evaluation_result.json",
      "• that evaluator also runs as an outer refiner (--feedback-mode evaluator) and an inner plan refiner in the "
      "predecessor pipeline"],
     "Evaluation and baselines", "COMPARISON", INK),

    (["Code2Video (upstream Manim agent, vendored)  ->  TVG_remotion (first Remotion renderer + provider tests)  "
      "->  Teaching_Video_Generation / teachgen (two-phase plan + render, MLLM review loop, evaluator refiners)  "
      "->  EduHarness (scene-level checkpoints, deterministic guards, patch-first repair, non-linear bundle)"],
     "How this method got here", "LINEAGE", MUTED),
]
for lines, title, kicker, accent in rail_boxes:
    mono = kicker == "CHECKPOINTS"
    hh = box(RL, ry, RW, lines, title=title, kicker=kicker, accent=accent,
             body_size=11.3 if not mono else 10.4, pad=12,
             body_font=MONO if mono else SANS)
    ry += hh + 16

# ------------------------------------------------------------- legend + title
legend_y = max(main_bottom, ry) + 4
items = [(PRIMARY, "model call (tokens / images / TTS are billed here)"),
         (SECOND, "local, deterministic, no key required"),
         (DANGER, "gate, measured failure, or hand-off to a human"),
         (MUTED, "context")]
lx0 = ML
for color, label in items:
    out.append(f'<rect x="{lx0}" y="{legend_y-9}" width="15" height="11" rx="2" fill="{PANEL}" stroke="{color}" stroke-width="1.4"/>')
    out.append(f'<rect x="{lx0}" y="{legend_y-9}" width="3.2" height="11" fill="{color}"/>')
    text_el(lx0 + 22, legend_y, label, 11.4, INK, 0.78)
    lx0 += 24 + len(label) * 6.1 + 34
H = legend_y + 34

head = [
    f'<rect x="0" y="0" width="{W}" height="{H}" fill="{GROUND}"/>',
    f'<text x="{ML}" y="48" font-family="{SANS}" font-size="26" font-weight="700" fill="{INK}">'
    f'EduHarness — from a structured request to an audited, non-linear lesson</text>',
    f'<text x="{ML}" y="72" font-family="{SANS}" font-size="13" fill="{INK}" fill-opacity="0.72">'
    f'The method in /data/chenqingyue/education_video: one LLM plans, four sandboxed renderers draw, deterministic guards measure,</text>',
    f'<text x="{ML}" y="89" font-family="{SANS}" font-size="13" fill="{INK}" fill-opacity="0.72">'
    f'an independent vision reviewer audits every scene against its own key elements, and only scenes that pass both are packaged.</text>',
    f'<text x="{W-ML}" y="48" font-family="{MONO}" font-size="11.6" fill="{INK}" fill-opacity="0.58" '
    f'text-anchor="end" letter-spacing="0.08">python -m eduharness --request-json examples/sample_request.json</text>',
    f'<text x="{W-ML}" y="68" font-family="{MONO}" font-size="11.6" fill="{INK}" fill-opacity="0.58" '
    f'text-anchor="end" letter-spacing="0.08">stages:  1 | 2-prepare | 2-render | 2-review | 3</text>',
    f'<text x="{W-ML}" y="88" font-family="{MONO}" font-size="11.6" fill="{INK}" fill-opacity="0.58" '
    f'text-anchor="end" letter-spacing="0.08">python -m eduharness.studio --runs-dir runs --port 8080</text>',
    f'<line x1="{ML}" y1="100" x2="{W-ML}" y2="100" stroke="{INK}" stroke-opacity="0.2" stroke-width="1"/>',
]

defs = ['<defs>']
for mid, col in (("ah", INK), ("ahB", PRIMARY), ("ahG", SECOND), ("ahR", DANGER)):
    defs.append(
        f'<marker id="{mid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        f'orient="auto-start-reverse"><polygon points="0,1 10,5 0,9" fill="{col}"/></marker>'
    )
defs.append('</defs>')

svg = (
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {int(H)}" width="{W}" height="{int(H)}" '
    f'role="img" aria-label="Detailed flowchart of the EduHarness teaching-video generation method">'
    + "".join(defs) + "".join(head) + "".join(out) + "</svg>"
)

dst = Path("/data/chenqingyue/education_video/eduharness/docs/audit/eduharness-method-flowchart.svg")
dst.write_text(svg, encoding="utf-8")
print("wrote", dst, len(svg), "bytes;  canvas", W, "x", int(H))
