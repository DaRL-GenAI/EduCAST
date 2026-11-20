# EduHarness

Agent harness for **interactive teaching media**: an LLM plans a lesson, sandboxed
tool adapters render each scene (image / Manim / Remotion / parameterized
interactive templates), deterministic guards plus an independent VLM reviewer
audit every scene, and the result is packaged as a non-linear **EduBundle**
with narration and a hybrid video/interactive player.

## Pipeline

```
Stage 1  Main Agent   → LessonBlueprint (scenes + key_elements + narration) + style_config.json
Stage 2  prepare      → API work only: tool specs, diffusion images, TTS narration      (needs key)
         render       → local: Manim (layout-guarded), Remotion beats, image compose,
                        interactive preview; narration muxed into video                 (offline)
         review       → guards (layout / blank frames / DOM overflow) + one structured
                        VLM verdict per scene; failed scenes get targeted repairs         (needs key)
Stage 3  bundle       → EduBundle (manifest.json + media + interactive JSON + player)   (offline)
```

| Scene type    | Tool                          | What the Executor emits                                    |
|---------------|-------------------------------|------------------------------------------------------------|
| `image`       | gpt-4o → gpt-image-2 + Pillow | expanded English prompt → complete teaching diagram with short labels, placed in the board's `main` region without cropping or recoloring |
| `manim`       | Manim CE (restricted subprocess) | `construct()` body only — theme header + layout guard injected |
| `remotion`    | Remotion 4 (pinned template)  | one *beat* spec: `title_card` / `bullets` / `formula` / `compare` / `steps` / `recap` / `stat_row` |
| `interactive` | trusted zero-dependency JS runtime | JSON parameters for `physics_lever`, `multiple_choice`, `drag_sort`, `fill_blank`, `number_line` |

A lesson has three visual contracts, and only three:

**1. The opener is its own stage.** `title_card` is the one beat that is not a
board: `TitleCard` in `remotion_template/src/SceneBeat.tsx` draws a cast leaning
in from the two bottom corners — a pair per corner, overlapping at the shoulder,
bodies running off the bottom edge — while the title and subtitle surface in the
middle over about 1.5s. The cast, its proportions and the corner bite live in
`presentation.TITLE_CAST*`; `remotion.render_fallback_slide` paints the same
still with Pillow, so a missing Chrome does not change the composition.

**2. Image scenes are generated art inside the board.** A text model expands the
scene brief, audience, narration and key elements into a detailed English prompt;
`gpt-image-2` draws one `1536x1024` teaching diagram at high quality, labels
included; `compose_concept_image(..., brief=scene)` then places that diagram in
the board's `main` region — aspect-contained, never cover-cropped, and *not*
palette-snapped, because quantizing shreds the small labels the model drew.
`blend_ground()` fades the art's own near-white ground into the board background
so no panel edge shows. The final prompt is saved in
`work/<scene-id>/image_prompt.txt`, and image checkpoints prepared by older runs
keep the pre-board compositor until they are regenerated.

**3. Everything else is the shared board.** Ordinary Manim and Remotion beats
draw the Code2Video-style teaching board from one measurement — a fixed title
band, left lecture column, right visual column, A1-F6 anchor grid and a dedicated
result band (`schema.teaching_board`). Interactive scenes stay standalone
practice panels.

### What makes the loop converge

* **Key elements.** The planner lists 2–5 checkable things that must be visible
  per scene. The reviewer must classify each as present/missing; a missing one
  is a blocking defect, so "looks fine but shows the wrong thing" cannot pass.
* **Deterministic guards before the VLM.** The Manim theme header wraps the
  scene in `_EduGuardScene`, which measures text bounding boxes after every
  `play()`/`wait()` and samples motion at 0.25-second intervals. `guard.json`
  records text outside the frame, text/text collisions and text intersecting
  sampled Bezier strokes or filled geometry (including axes and arrow shafts).
  The guard does not move labels or detach them from their targets. Those timestamps become extra review
  frames, and guard *blockers* fail the scene even if the VLM is lenient.
  Interactive previews get a DOM-overflow audit; videos get blank-frame checks.
* **Blocking vs. minor.** Reviews return `blocking_issues` / `minor_issues` /
  `missing_key_elements`; a scene passes only with zero blocking issues and
  `score >= EDUHARNESS_PASS_SCORE` (default 7). Minor nits never burn a repair
  round. A reviewer outage is retried and then flagged for a human (`debug/<id>_HITL.txt`)
  — it never regenerates the scene and never passes it.
* **Diff-first repairs, but only once.** When the prior artifact is available
  the reviewer emits grounded `ops` (replace/set) that are applied locally. If
  a patched artifact fails again the defect is structural, so the next round
  regenerates from the prior artifact + feedback + guard findings (Remotion may
  switch beat). `--stage 2` resumes from the checkpoints and re-does only the
  scenes that still fail.
* **Narration.** Each scene's narration is synthesized once (cached by text
  hash), muxed into videos (the shorter track is padded), and shipped as mp3 for
  image/interactive scenes. The player shows captions and waits for narration.

## Install

System deps: `ffmpeg`, a LaTeX toolchain for `MathTex` (optional; plain `Text`
is used otherwise), Node ≥ 16 for Remotion, pango/cairo for Manim.

```bash
# Debian/Ubuntu
sudo apt-get install -y ffmpeg libcairo2-dev libpango1.0-dev fonts-liberation \
     texlive-latex-base texlive-latex-recommended texlive-latex-extra dvisvgm
pip install -r requirements-render.txt      # openai, pydantic, manim, playwright, …
python -m playwright install chromium       # interactive previews + Remotion's browser
(cd remotion_template && npm ci)            # pinned Remotion 4.0.200
```

`pip install -r requirements.txt` alone is enough for the API-only stages
(`1`, `2-prepare`, `2-review`). Dev/test: `pip install -r requirements-dev.txt`.

On a host whose image is reset periodically — anything installed under `/usr`
disappears, a mounted volume does not — use the scripted setup instead. It puts
the venv, Chrome, and the extracted `-dev` headers on the persistent volume and
only re-links `ffmpeg` into `/usr/local/bin`:

```bash
scripts/setup_env.sh          # idempotent; EDUHARNESS_STORE picks the location
source "$EDUHARNESS_STORE/env.sh"
```

Two failure modes this exists to prevent, both of which look like a working run:

* **A Chrome torso.** Unzipping only the `chrome-headless-shell` executable
  gives a binary that answers `--version` and then dies at launch with
  `Invalid file descriptor to ICU data received`; every Remotion scene silently
  becomes a static slide (`render_mode: ffmpeg-slide-fallback`).
  `browser_executable()` now skips a build with no `icudtl.dat` beside it.
* **A shared library path that leaks.** The bundled ffmpeg needs its own
  `LD_LIBRARY_PATH`; exporting that globally hands conda's `libicu` to Chrome
  and breaks it the same way. The wrapper in `$EDUHARNESS_STORE/bin` keeps the
  path inside the ffmpeg process.

## Run

```bash
export OPENAI_API_KEY=sk-...          # or put it in .env
python -m eduharness --request-json examples/sample_request.json
python -m eduharness.serve runs/<request_id>/bundle   # range-capable preview → http://127.0.0.1:8765/
```

Single stages (same CLI as before; the Colab notebooks still work):

```
--stage 1          plan
--stage 2          one-machine prepare → render → review loop with targeted repairs
--stage 2-prepare  API work for scenes that need it (targets failed scenes when a review exists)
--stage 2-render   local rendering only, no API key required
--stage 2-review   audit rendered outputs
--stage 3          bundle + player, no API key required
```

Every run writes `usage.json` (per-call tokens, images, TTS characters, USD).

### Request fields

`examples/sample_request.json`: `topic`, `audience`, `learning_goal`,
`source_text`, `preferred_theme`, `language`, `max_review_rounds` (1–6),
`enable_manim`, `enable_remotion`, `enable_image`, `enable_narration`, `voice`,
`parallel`, `allow_unreviewed_bundle`.

### Two endpoints: chat via a relay, media via the official API

Text + vision (planner, executors, reviewer) and image + TTS can use different
endpoints and keys. A company relay that only forwards chat completions is
enough for everything except `image` scenes and narration:

```bash
# text + vision through the relay
export EDUHARNESS_TEXT_BASE_URL=http://token.example.com/v1
export EDUHARNESS_TEXT_API_KEY=sk-relay…
export EDUHARNESS_TEXT_MODEL=gpt-5.6-sol EDUHARNESS_VISION_MODEL=gpt-5.6-sol
# image + TTS through the official API (omit → image scenes and narration are disabled)
export EDUHARNESS_MEDIA_API_KEY=sk-proj…      # or just OPENAI_API_KEY
```

Relays that enforce strict JSON schemas are handled automatically (the provider
falls back to `json_object` with the schema in the system prompt), and 502/503/504
are retried.

**A relay may be fine for generation and still fail the reviewer.** The audit
sends several frames plus a long structured prompt in one call; a relay with a
short upstream timeout cuts that off (`Upstream stream ended without a terminal
response`) while ordinary text calls sail through. Shrink the payload with
`EDUHARNESS_FRAMES_PER_VIDEO` / `EDUHARNESS_FRAME_WIDTH` / `EDUHARNESS_VISION_DETAIL`,
or point `EDUHARNESS_MEDIA_*`-style split config at the official API for review.
The pipeline never passes a scene it could not audit: every failure is recorded
as `review_error` and lands in `debug/<id>_HITL.txt`.

### Preview

```bash
python -m eduharness.serve runs/<id>/bundle          # range-capable local server
python -m eduharness.preview runs/<id>                # ONE self-contained HTML (assets inlined)
```

### Render Studio

Use the local Studio for long-running jobs and recovery after a notebook or
browser disconnect. It scans every run checkpoint, shows the active renderer
and review state, and starts the existing CLI in the background; the browser is
not the owner of the generation process.

```bash
python -m eduharness.studio --runs-dir runs --port 8080
# open the forwarded http://127.0.0.1:8080/ address
```

The Studio persists a request before planning, previews each scene, opens the
player or standalone HTML, copies the exact next-stage command, and exposes
`.studio/job.json` plus `.studio/job.log` for background jobs. For a historical
run without `request.json`, the request is inferred from its blueprint when you
start a job, so the existing checkpoints remain intact until that point.

### Public showcase

A separate read-only server publishes the homepage and the three featured lesson
bundles. It uses the current Studio design, relocated classroom characters, and
original pastel number trail. Creation controls are replaced with links to the
lessons and pipeline; private requests, logs, and job endpoints are unavailable.

```bash
python -m eduharness.studio.public --port 8091
/data/chenqingyue/bin/cloudflared tunnel --no-autoupdate --protocol http2 --url http://127.0.0.1:8091
```

The active deployment stores its URL, process IDs, and logs in
`/data/chenqingyue/eduharness/public-showcase/`. The public URL is in `url.txt`.
Quick-tunnel hostnames can change when the tunnel is restarted; both the server
and tunnel need to stay running. The local editing Studio remains on port 8080.

### Environment knobs

| Variable | Default | Meaning |
|---|---|---|
| `EDUHARNESS_TEXT_MODEL` / `EDUHARNESS_VISION_MODEL` | `gpt-5` | planner / executor / reviewer models |
| `EDUHARNESS_TEXT_BASE_URL`, `EDUHARNESS_TEXT_API_KEY` | `OPENAI_*` | endpoint/key for chat + vision |
| `EDUHARNESS_MEDIA_BASE_URL`, `EDUHARNESS_MEDIA_API_KEY` | `OPENAI_*` | endpoint/key for image + TTS |
| `EDUHARNESS_IMAGE_MODEL`, `EDUHARNESS_IMAGE_QUALITY` | `gpt-image-2`, `high` | complete concept illustrations |
| `EDUHARNESS_IMAGE_PROMPT_MODEL` | `gpt-4o` | expands the teaching brief into an English image prompt |
| `EDUHARNESS_TTS_MODEL` | `gpt-4o-mini-tts` | narration |
| `EDUHARNESS_REASONING_EFFORT` | `medium` | gpt-5 reasoning effort (planner uses `high`) |
| `EDUHARNESS_MAX_COMPLETION_TOKENS` | `16000` | gpt-5 completion cap (reasoning tokens included; doubled automatically when a reply is truncated) |
| `EDUHARNESS_PASS_SCORE` | `7.0` | reviewer pass threshold |
| `EDUHARNESS_FRAMES_PER_VIDEO` | `5` | uniformly sampled review frames (+ guard-flagged ones) |
| `EDUHARNESS_FRAME_WIDTH`, `EDUHARNESS_VISION_DETAIL` | `1280`, `high` | review payload size — shrink both for a relay that struggles with multi-image calls |
| `EDUHARNESS_AMBIENT_PARTICLES` | `46` | ambient dots behind every Manim scene (`0` disables) |
| `EDUHARNESS_PARALLEL` | request `parallel` (4) | scenes prepared/rendered/reviewed concurrently |
| `EDUHARNESS_MANIM_QUALITY`, `EDUHARNESS_MANIM_TIMEOUT` | `l`, `360` | Manim CLI quality / seconds |
| `EDUHARNESS_MANIM_CONTAINER_IMAGE` | – | run Manim inside `docker run --network none` |
| `EDUHARNESS_FFMPEG`, `EDUHARNESS_FFPROBE` | auto | override binaries (the first *working* one on PATH is used) |
| `EDUHARNESS_MANIM` | auto | Manim CLI: PATH first, then `$EDUHARNESS_STORE/.render-env/bin/manim` |
| `EDUHARNESS_BROWSER_EXECUTABLE` | auto | Chrome for Remotion (taken as given; otherwise the first *complete* build of Remotion's download, Playwright's cache, `$EDUHARNESS_STORE/runtime`) |
| `EDUHARNESS_STORE` | `../../eduharness/eduharness` | where `scripts/setup_env.sh` keeps the persistent toolchain |

## Run directory

```
runs/<id>/
  blueprint/lesson_blueprint.json, style_config.json
  prepared_scenes.json     API checkpoints (spec paths, narration path/seconds, attempt)
  rendered_scenes.json     local outputs + guard report + review verdict per scene
  work/<scene>/            manim_spec.json / remotion_spec.json / interactive_spec.json,
                           <scene>.py, guard.json, narration.mp3, logs
  media/, interactive/, frames/
  debug/<scene>_review_r<n>.json   full verdict + frames + guard evidence per round
  debug/<scene>_HITL.txt           scenes that need a human after the budget
  bundle/                  manifest.json, media/, interactive/, index.html, player.js
  usage.json               API cost ledger
```

## Hybrid Colab / local workflow

Unchanged: run `1` and `2-prepare` where the API is reachable, sync the run
directory, run `2-render` locally (no key), sync back, run `2-review`, repeat
until every scene passes, then `3` locally and preview with `python -m eduharness.serve`. `notebooks/` contains the Colab
runners; `scripts/pack_colab_src.sh` packs the source.

## The Manim scene kit

Shared text is shaped at font size 96 and uniformly scaled to the requested
display size. This avoids uneven glyph advances from shaping sidebar text at
very small Pango sizes. Lecture wrapping uses measured text width and keeps one
size across the column. Inter files are registered from `eduharness/assets/fonts/inter`
inside each renderer process; text SVG caches are namespaced by font file
contents and shaping version, so installing a font cannot reuse an old fallback
SVG. Disabling animation caching alone does not invalidate Manim's text SVGs.

A model asked to draw on a blank 14×8 canvas produces three shapes floating in
the middle — and the safety rules that keep text from overlapping push it further
towards emptiness. So the theme header ships a kit of composed, guard-safe
primitives and the prompt tells the model to build from them:

| helper | what it composes |
|---|---|
| `title_bar(text, kicker)` | top band: micro-label, bold title, accent rule |
| `card(content, label)` / `chip(value, unit, name)` | bordered panel · KPI tile matching the page's stat strip |
| `callout(text)` | the verdict block: soft ground, thick leading rule |
| `self.annotate(target, text, RIGHT, obstacles=(diagram,))` | nearby clear label and leader that follow their target |
| `row()` / `column()` / `place()` | groups auto-fitted into the safe frame |
| `bar_chart(values, labels)` | small comparison chart with value labels |
| `reveal()` / `emphasize()` / `swap()` | staggered entrance · pulse · in-place step change |

Each helper keeps itself inside the safe frame, so richer scenes do not mean more
layout-guard failures. The prompt also asks for a full frame — title band, a
content band that actually fills the middle, one worded takeaway, and 3–5 beats
paced to the narration.

For annotations, place the complete diagram, including its future curve states,
before calling `self.annotate`. The helper tries clear positions within one grid
cell of the target without reducing type size. Supply future shapes through
`obstacles` to reserve space before they become visible. A label and its short
leader move together, including when the target is resized. If no nearby space
fits, the render fails with a concrete instruction to reserve a label lane,
shorten the text or remove the previous state's annotation. Keep the target
before its annotation when grouping them; create a fresh annotation for a new
target. The global `annotate` helper remains available for older checkpoints.

The planner now describes annotation ownership, nearby clear space and label
lifetime per animation step. Remove an obsolete label before moving to the next
state, then show the new value. Review reports text/curve/axis collisions and
stale labels as blockers, including observations mistakenly put in a minor
field. A collision inside a diagram is repaired through its annotation call or
state transitions, rather than translating the entire diagram.

**Film chrome.** Ordinary Manim and Remotion scenes carry the shared title,
lecture, result, and progress treatment, so the clips read as one produced
piece rather than a pile of exports. Title cards remain intentionally quiet.

### Formulas: two paths, neither of which may leak markup

`MathTex` needs a LaTeX toolchain. Where one is missing — Colab, a slim
container — the renderer rewrites the scene's formulas into Unicode rather than
crashing, and two rules keep that from degrading the output.

**Nothing raw ever reaches a frame.** `_latex_to_plain` is a real converter, not
a regex strip: it resolves Greek names, operators and relations, maps sub- and
superscripts to Unicode where the glyphs exist and to `_x` / `^x` where they do
not, treats `\mathrm` / `\text` / `\mathbf` and friends as transparent, and
turns every LaTeX spacer into one real space. So
`\tau_{\mathrm{cw}} = \tau_{\mathrm{ccw}}` reads as `τ_cw = τ_ccw`, never as
`tau_mathrmcw`. Property tests assert no backslash or brace survives conversion.

**The downgrade is never persisted.** A plain-text rewrite is a render-time
fallback, not a repair: writing it back into `manim_spec.json` would burn the
formulas into the run, and a later re-render on a machine that *does* have TeX
could never recover them. `_render_manim_checkpoint` therefore returns a
`durable` flag alongside the body it used — only a genuine fix (an API traceback
repair) is promoted into the spec; a lossy attempt is written to
`work/<scene>/<scene>_rendered_body.py` for repro and nothing else.

A related repair runs at the other end. Models emitting code inside JSON often
double-escape a raw string, so `MathTex(r"\\tau")` arrives with a backslash
that LaTeX reads as a line break followed by the bare word `tau`.
`normalize_tex_escapes` rewrites those literals via the AST, and it is called
from `assemble_script` — the one choke point every render path funnels through,
including a body replayed from a stored spec.

## Style boards

`schema.THEMES` holds the named boards; the planner picks a name and `_sanitize`
pins the exact values, so the media and the player chrome can never drift apart.

| board | ground | ink | primary / secondary / danger |
|---|---|---|---|
| `studio_light` (default) | `#FAFBF8` | `#17201B` | `#356B8F` / `#16734A` / `#B4423D` |
| `academic_dark` | `#12161B` | `#ECF1F4` | `#6FA8D6` / `#4FC08D` / `#E0766F` |

Both boards use Inter, installed system-wide so Manim (Pango) and Remotion
(headless Chrome) resolve the same face the web chrome asks for.

A diffusion model only ever *approximates* a hex code, so for **isolated art**
the palette is enforced rather than requested: `snap_to_board()` smooths the
model's grain,
quantizes the flat art, merges near-identical clusters and maps each one onto an
exact board colour — ground by area, ink/muted by lightness, accents by hue.
Classification uses HSV saturation rather than absolute chroma, because absolute
chroma under-reads a dark teal stroke and HLS saturation over-reads a cream ground.
Concept images are the exception: they carry their own labels, and quantizing
type that small leaves coloured fringes, so `compose_concept_image` passes
`snap_art=False` and only blends the art's ground into the board.

Every scene carries the same ambient particle texture: Remotion beats animate a
seeded field (position is a pure function of the frame, so parallel workers stay
deterministic), and Manim injects a static dot field from `_EduGuardScene.setup()`
— drawn first so it sits behind the content, and made of Dots so the text guard
ignores it. Stills get the same field composited on top, and the player page
carries a much fainter version on a fixed canvas that is drawn once (no
animation loop) when the viewer prefers reduced motion.

After editing a board, re-render and re-audit an existing run:

```bash
python -m eduharness --request-json … --run-dir runs/<id> --stage 2-render --force
python -m eduharness --request-json … --run-dir runs/<id> --stage 2-review
```

`--force` drops the stored verdicts rather than reusing them: they describe the
previous look.

## Look and feel

The Studio homepage uses a warm white, sage, and terracotta palette, local DM Sans
fonts, and the original classroom characters. A working torque experiment opens
the page; selectable pipeline stages explain planning, preparation, rendering,
review/repair, and packaging.

The lesson gallery shows Quadratics first, followed by Torque and Lever Balance
and Ohm’s Law. Chapter counts, runtime, and practice counts come from the actual
bundle manifests. Selecting a card replaces the embedded player in place; build
history selection remains inside the Studio desk. Example builds with outstanding
reviews are identified as previews.

The shared player supports `?layout=board`: a large stage and chapter sidebar on
desktop, with an expanding practice area on mobile. The Studio listens only to
height messages from its own embedded player. Existing narration, captions,
chapter navigation, resume state, and interactive checkpoints remain available.

After changing the player shell, refresh existing demos without regenerating
lesson media, calling a model, or changing manifests and review records:

```bash
python -m scripts.refresh_demo_players quadratics lever_v2_backup ohms_law
```

This generates cached video posters locally with ffmpeg and updates only each
bundle’s `index.html` and `player.js`. Future bundle generation also picks up
existing `media/<video-name>.poster.jpg` files. Frontend assets are in
`eduharness/studio/`; the persistent toolchain lives separately under
`/data/chenqingyue/eduharness/eduharness` on this host.

## Layout

```
eduharness/
  schema.py config.py pipeline.py
  providers/          # OpenAI (structured outputs, retries) + usage ledger
  stage1/             # Main Agent (planner)
  stage2/             # workflow (prepare/render/review), reviewer, guards, narration,
                      # adapters/ (image, manim, remotion, interactive), repair_apply/
  stage3/             # bundler, player, interactive_runtime.js
  templates/schemas/  # parameterized interactive specs + Pydantic validators
remotion_template/    # pinned Remotion project: SceneBeat with 5 beats
tests/                # offline tests (FakeProvider); browser test needs Playwright
```

## Tests

```bash
pytest -q
```
