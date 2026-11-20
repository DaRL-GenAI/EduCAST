# teachgen

**One OpenAI key + one topic → a narrated teaching video.** An orchestration layer
that unifies this repo's three production paths behind a single planner and a
single-key provider, then narrates, composites, and self-reviews the result.

```bash
export OPENAI_API_KEY=sk-...

# full run
python -m teachgen --topic "How the Fourier transform works"

# inspect the plan before spending money on media
python -m teachgen --topic "Vectors" --plan-only

# common options
python -m teachgen --topic "Vectors" --audience "high-school students" \
    --max-rounds 3 --score-threshold 8.0 --no-parallel --run-dir runs
```

## Two phases

- **Phase 1 — planner (text only).** topic → teaching content (objectives +
  per-segment spoken narration) → a `LessonPlan` that routes each segment to a
  renderer. Written to `runs/<topic>/lesson_plan.json` — review/edit before Phase 2.
- **Phase 2 — produce (media).** per segment: narrate (TTS + word timings) and render
  the visual → composite → nested feedback loop → `runs/<topic>/video/final.mp4`.

```
cli → pipeline ──┬─ planner:  content_writer → route ──────────────────► LessonPlan
                 └─ produce:  narrator + renderers → compositor ───────► draft.mp4
                                                          │
                                                    outer_reviewer
                                                    (score / classify)
                                                    │           │
                                              content_issues  visual_issues
                                                    │               │
                                             plan_refiner    visual_refiner
                                            (Inner Loop 1)  (Inner Loop 2)
                                                    │               │
                                             re-TTS + re-render   re-render only
                                                    └───────────────┘
                                                      next outer round
```

Everything generative (text, structured, vision, TTS, image) goes through one
`Provider` (`providers/openai_provider.py`) — that is why a single key suffices.
Vision review samples frames from the mp4 (OpenAI can't ingest video directly).

## Nested feedback loop

Phase 2 runs an **outer loop** (default ≤ 3 rounds) that drives two **inner loops**
based on what the reviewer finds wrong. Rounds stop early once `overall_score ≥
score_threshold` (default 8.0 / 10).

```
Outer loop  (≤ max_outer_rounds, stops when score ≥ score_threshold)
│
│  composite draft → OuterReviewer watches full video
│  → overall_score, content_issues[], visual_issues[]
│
├─ Inner Loop 1 — Plan refinement  (if content_issues)
│    plan_refiner rewrites narration and/or visual_brief for affected segments.
│    • narration changed → audio + visual both regenerate (re-TTS + re-render)
│    • visual_brief changed → visual only regenerates (audio reused)
│
└─ Inner Loop 2 — Visual refinement  (if visual_issues)
     visual_refiner rewrites visual_brief for rendering-broken segments.
     • audio is always reused (narration unchanged)
     • only visual cache is cleared → re-render only
```

**Issue classification** — the outer reviewer pre-classifies every problem:

| Category | Meaning | Fixed by |
|---|---|---|
| `content_issues` | narration wrong/unclear, or visual_brief too vague | Inner Loop 1 |
| `visual_issues` | rendering broken/ugly, but the approach is right | Inner Loop 2 |

The two inner loops are independent: a round can trigger both, one, or neither.
Each loop invalidates only the minimum cache entries needed, so unchanged segments
are never re-produced.

## The three renderers (plugins in `renderers/`)

| Modality        | Backend (reused from this repo)        | When the planner picks it          |
|-----------------|----------------------------------------|------------------------------------|
| `animation`     | **code2video** `code2video/agent.py` (Manim) | demos, derivations, processes — the workhorse |
| `concept_image` | **concept_image.py** (gpt-image-1)     | intuition, metaphor, one big idea  |
| `slide`         | **make_slide.py** parsing + PIL raster | **final recap/summary ONLY**       |

- `animation` drives code2video at **single-segment grain** (teachgen owns the
  outline, so its top-level `GENERATE_VIDEO` is bypassed). code2video's LLM calls are
  shimmed through teachgen's Provider, so the run stays single-key; its own Gemini
  video-feedback loop is disabled and teachgen's reviewer covers holistic feedback.
- `slide` rasterizes straight to PNG via Pillow (make_slide's palette + parsing),
  so **no LibreOffice/poppler** is needed.
- **Slides are reserved for the final recap.** `planner/route.py` enforces it: any
  non-final slide is demoted to a concept image, and the last segment is promoted to a
  recap slide. Renderer-failure fallback is `concept_image` (then slide) so the rule
  survives failures.

## Add a fourth path

1. Add a value to `Modality` in `schema.py`.
2. Add a `SegmentRenderer` in `renderers/` and `register()` it in `renderers/__init__.py`.
3. Add one line describing it to the planner's system prompt in `route.py`.

The pipeline, compositor, and feedback loop don't change.

## CLI options (feedback)

| Flag | Default | Effect |
|---|---|---|
| `--no-feedback` | off | Skip the entire feedback loop |
| `--max-rounds N` | 3 | Cap on outer loop iterations |
| `--score-threshold F` | 8.0 | Stop early when `overall_score ≥ F` |

## Requirements

See `requirements.txt`. Summary:
- **Python deps:** openai, pydantic, moviepy (1.x/2.x both work via `mpcompat.py`),
  pillow, python-pptx.
- **System:** `ffmpeg` (compositing, frame sampling, audio probing).
- **For `animation` only:** Manim Community (`manim`) + its native deps, plus
  code2video's own deps in `../code2video/requirements.txt`. Without Manim, animation
  segments fall back to concept images.

## Layout

```
teachgen/
  cli.py / config.py / schema.py / pipeline.py / mpcompat.py
  make_slide.py        slide text -> (title, bullets, diagram); reused by the slide renderer
  concept_image.py     concept -> image-prompt helper; reused by the concept_image renderer
  providers/   base + openai_provider (default) + gemini_provider (stub)
  planner/     content_writer (narration) + route (modality routing)
  renderers/   base + slide + concept_image + animation
  audio/       narrator (TTS + word timings)
  compositor/  compositor (visuals + audio -> mp4, yuv420p + faststart)
  feedback/
    _frames.py          shared video-frame sampler
    outer_reviewer.py   holistic video review → overall_score + classified issues
    plan_refiner.py     Inner Loop 1: rewrite narration / visual_brief
    visual_refiner.py   Inner Loop 2: rewrite visual_brief for broken renders
    reviewer.py         (legacy single-pass reviewer, kept for reference)
    router.py           (legacy router, kept for reference)
```

The `animation` renderer reuses `../code2video/` (agent.py + its `prompts/` and
`json_files/`). The slide and concept_image renderers reuse `teachgen/make_slide.py`
and `teachgen/concept_image.py` (imported as package modules). Code unrelated to this
pipeline (the original TeachingMonster baseline, evaluation scripts, standalone
runners) was archived under `../__trashcan__/`.

> Security: `code2video/api_config.json` contains a real OpenAI key in git history — revoke
> it and rely on the `OPENAI_API_KEY` env var instead.
