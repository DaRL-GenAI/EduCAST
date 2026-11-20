# Teaching Video Generator

> **Note.** This copy omits `code2video/`. Clone [Code2Video](https://github.com/showlab/Code2Video) into `legacy/code2video/` before running `teachgen` with the animation renderer.


**One OpenAI key + one topic → a narrated teaching video.**

This repo has two parts:

| Directory     | What it is                                                                 |
|---------------|----------------------------------------------------------------------------|
| **`teachgen/`** | The orchestrator and entry point. Plans a lesson, routes each segment to the best visual, narrates it, composites the video, and runs an MLLM review loop. |
| **`code2video/`** | The upstream **Code2Video** project — generates polished Manim animations. teachgen drives it as its `animation` renderer. See `code2video/README.md`. |
| `runs/`        | Generated output (`runs/<topic>/...`).                                     |

## Quickstart

```bash
pip install -r requirements.txt          # core deps (+ system ffmpeg)
export OPENAI_API_KEY=sk-...

python -m teachgen --topic "How the Fourier transform works"

# just the plan (cheap), before producing media:
python -m teachgen --topic "Vectors" --plan-only
```

The output video lands at `runs/<topic>/video/final.mp4`. See **`teachgen/README.md`**
for the architecture, the two-phase flow, the three renderers, and how to extend it.

## Code logic

The whole run is driven by `teachgen/pipeline.py::generate(cfg)`, which builds a single
`Provider` (one OpenAI key behind one interface) and executes two phases. Every stage
communicates only through the pydantic schema objects in `teachgen/schema.py`
(`LessonPlan`, `Segment`, `VisualAsset`, `NarrationAudio`, `ReviewResult`) — never
through each other's internals. That decoupling is what lets renderers be swapped and
the feedback loop target one segment at a time.

```
cli → Config.from_env → pipeline.generate
        │
        ├─ Phase 1  phase1_plan
        │     content_writer.write_content   topic+audience → objectives + spoken segments (text)
        │     route.plan_lesson              each segment → modality + visual_brief → LessonPlan
        │     _enforce_slide_only_last       hard rule: slide only on the final recap segment
        │     → runs/<topic>/lesson_plan.json   (human-inspectable checkpoint; --plan-only stops here)
        │
        └─ Phase 2  phase2_produce  (loop up to max_feedback_rounds + 1 times)
              _produce_assets       per dirty segment, in a thread pool:
                  narrator.narrate      narration → TTS audio + word timings (audio duration = segment length)
                  _render_segment       dispatch to planned renderer; fall back concept_image → slide on failure
              compositor.assemble   visuals + audio → draft_r<n>.mp4 / final.mp4
              reviewer.review       sample 12 frames → MLLM critique → ReviewResult (score + fix_actions)
              router.apply          turn blocking critiques into the smallest plan edit; return dirty segment ids
                  → invalidate caches for changed segments only; loop re-does just those
```

**Phase 1 — plan (text only).** `content_writer` asks the model for objectives plus an
ordered list of spoken segments. `route.plan_lesson` then assigns each segment a
`Modality` (`animation` / `concept_image` / `slide`) and a concrete `visual_brief`.
`_enforce_slide_only_last` deterministically guarantees the rule the prompt only
requests: any non-final `slide` is demoted to `concept_image`, and the last segment is
promoted to `slide`, so the lesson always closes on a recap deck. The plan is written to
`lesson_plan.json` as the review checkpoint (`--plan-only` returns here).

**Phase 2 — produce (media + feedback loop).** Two caches keyed by segment id
(`audio_cache`, `visual_cache`) mean each feedback round only redoes what changed.
For every *dirty* segment, `_produce_assets` runs `narrator.narrate` (the TTS duration
defines the segment's length) and `_render_segment`, fanned out across a
`ThreadPoolExecutor` when `parallel` is set. `_render_segment` tries the planned renderer
and degrades gracefully along `planned → concept_image → slide` so a failed animation
never injects a stray slide on a non-recap segment. `compositor.assemble` stretches
static images to the narration duration and freezes/pads animation clips to fit, then
writes an H.264 mp4 (`yuv420p + faststart`).

**Feedback loop.** Unless `use_feedback` is off, `reviewer.review` samples 12 frames from
the composite (OpenAI can't ingest mp4 directly), has the vision model critique
clarity / alignment / pacing, and structures the notes into a `ReviewResult`. If there
are no blocking issues the draft is finalized; otherwise `router.apply` converts each
blocking critique into the smallest change (`rewrite_narration`, `replan`, `re_render`,
`adjust_timing`), mutates the plan in place, and returns the set of segment ids to redo.
The pipeline drops only those ids from the caches and loops; the final round always
writes `final.mp4`.

## Install notes

- **Core** (`requirements.txt`): planner + slide + concept-image + audio + compositing.
- **System:** `ffmpeg` is required. LibreOffice is **not** (slides rasterize via Pillow).
- **Animation renderer (optional):** needs Manim + code2video's own deps —
  `pip install -r code2video/requirements.txt`. Without Manim, animation segments
  fall back to concept images.

## Layout

```
code2video/   Manim animation engine (upstream Code2Video) + prompts/, json_files/, assets/
teachgen/     orchestrator: planner, renderers, audio, compositor, feedback
              + make_slide.py and concept_image.py (the slide / image helpers)
runs/         generated lessons
```

