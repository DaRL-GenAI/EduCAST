# EduCAST minimal reproducibility release

Baseline: DaRL-GenAI/EduCAST commit `539a045bfde7986d28d0bc932959d2615ce5abf0`, source subtree `src/eduharness`.
The original baseline is preserved. The initial runtime fixes and the subsequent review-loop fixes are documented separately below. The delivery contains `review-loop.patch` relative to the prior minimal release, a SHA256 file inventory, and the exact runtime source manifest.

## Changes

1. Respect `enable_remotion=false` when shaping the lesson opener. Previously the last sanitizer step silently converted the first teaching scene into Remotion and replaced its teaching requirements.
2. Skip inaccessible individual media-tool candidates instead of aborting PATH resolution.
3. Consume discarded FFmpeg output through subprocess pipes, supporting hosts where `/dev/null` cannot be opened for writing. Remotion uses `run(check=True)`, which drains these pipes.

The initial runtime fixes did not alter prompts or review criteria. The follow-up changes strengthen the review instructions and correct the first-scene review contract; pass thresholds, repair budgets and strict bundle rules remain unchanged. The sample is a small Manim lesson plus an interactive question; the planner remains model driven.

## Install and run on a normal Linux host

Use Python 3.10 or later. Manim needs Cairo/Pango development libraries and a compiler if wheels are unavailable; install these using your system's approved method. FFmpeg and FFprobe must be executable. Playwright also needs its matching Chromium build and the browser system shared libraries; downloading Chromium alone does not install those libraries. Native formula rendering additionally needs LaTeX and dvisvgm; a `manim-no-latex` result is a declared downgrade. Remotion, when enabled, additionally needs Node 18+, npm/npx and installation of the template dependencies using `npm ci`. Keep all virtualenvs, downloads and browser caches in your own working directory.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-render.txt
PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright" .venv/bin/python -m playwright install chromium
```

Set `OPENAI_API_KEY` in the process environment (never commit it), then:

```bash
PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright" .venv/bin/python -m eduharness \
  --request-json examples/repro_request.json --run-dir runs/repro
```

`requirements-observed.txt` records the important versions used in this audit; it is an observed configuration, not a full platform lock. The first audit reused Manim/Playwright. A subsequent fresh virtualenv installation and new Chromium download are documented below; the operating system was not rebuilt.

## Resuming without regenerating the lesson

The CLI supports `--stage 2-render --force --no-repair`, `--stage 2-review`, and `--stage 3`. Use the same request and run directory for all stages. Cached `review_error` results are retried on stage-2 resume. To re-audit already passed output, use `--stage 2-review --force`; without `--force`, passed scenes are skipped.

Never enable `allow_unreviewed_bundle` to claim successful reproduction. Check `rendered_scenes.json`: `ffmpeg-slide-fallback` and `manim-safe-fallback` do not demonstrate native renderer success. Declare any `manim-no-latex` downgrade. A real initial PASS does not prove the repair path actually ran.

## Restricted environment adapter

`scripts/node_stdio_pipe.cjs` is optional and is NOT loaded by default. On hosts where Node cannot use `/dev/null`, enable it with `NODE_OPTIONS="--require=$PWD/scripts/node_stdio_pipe.cjs"`. It changes only explicit array `ignore` entries of three-argument `child_process.spawn` into drained pipes. It is not a general Node compatibility patch. Chromium itself may additionally require `--no-zygote --single-process` in a local executable wrapper. These are environment adaptations, not model changes; the filesystem guard must remain active.

See `evidence/verification.json` for actual tested branches and limitations. Offline FakeProvider checks are never counted as real API generation or real vision review.

## Verified result (2026-11-24)

A fresh, real API request solving x + 2 = 5 produced a native Manim video, narration and a multiple-choice question. Manim initially failed visual review (score 5, adherence 6); feedback patched the generated artifact, native rendering ran again, and a fresh visual review passed (9/9). The interactive scene passed (9/9). Strict stage 3 produced a two-scene player with unreviewed output disabled. Eight API calls cost an estimated $0.346. The exact successful request is in examples/repro_linear_request.json; model generation remains stochastic.

Two more complex torque runs exhausted the three-round repair budget and were correctly blocked by the strict bundle gate. This release demonstrates a real repair loop on one simple case, not universal visual quality or reproduction of the original demo. Native Remotion and image generation were not validated in this run. That linear-example run reused the renderer environment; the subsequent fresh-environment audit below used a different topic.

On this write-restricted audit host, third-party Manim needed a task-local output sink instead of /dev/null, and Chromium used a local executable wrapper. These are host adaptations. The regular output file is not semantically identical to the null device. Missing dvisvgm and its shared libraries were downloaded from Ubuntu and checked against package SHA256 metadata for the formula regression test.

## Review follow-up fixes

The real API result above uses these follow-up changes. Offline regression tests also exercise reject -> feedback to generation -> render -> re-review, and recovery from a cached reviewer outage without regenerating or consuming a generation attempt.

Video evidence scales with duration (roughly one sample per two seconds, up to 16 base samples by default), plus Manim boundary frames. Explicit higher frame settings, Remotion extras and layout-guard timestamps remain respected. This is still sampled visual review, not continuous video/audio inspection or automated interaction testing. The reviewer must check requested visual demonstrations and cannot infer click behavior from a screenshot. Pass thresholds and generation budgets are unchanged.

Resuming a run now retries cached review errors automatically. Use the latest `rendered_scenes.json` as the verdict; old HITL text files can remain from an earlier outage. The final-linear-smoke player is the new verified example; earlier preview outputs are historical.

First-scene title-card treatment is now limited to Remotion; a first Manim teaching scene receives the teaching-board review contract. Resumed repair also applies a requested tool change before preparing its next attempt.

Text-containing swap transitions now fade out, replace the object in its parent, and fade in. Pure geometry retains ReplacementTransform. Regression cases cover Text, MathTex, grouped text and parent-child replacement. This prevents glyph-morph artifacts without changing review thresholds.


## Fresh dependency installation and new-topic audit (2026-11-24)

A new Python 3.10.20 venv with system site-packages disabled was populated from downloaded distributions, with Cairo/Pango Python extensions rebuilt. `pip check` passed; a newly downloaded Playwright Chromium launched successfully. `requirements-fresh-verified.txt` records all installed Python versions (an observed dependency snapshot, not an OS lock). On a Linux host with the native prerequisites above, use that file instead of `requirements-render.txt` to match these Python versions. Base Python, the compiler and LaTeX were reused, and FFmpeg/FFprobe binaries came from existing distributions. This was not a clean-OS or container rebuild. The audit host also required task-local native libraries and executable wrappers.

`examples/repro_area_request.json` tests a new topic: a 4-by-3 area grid and a 5-by-2 multiple-choice check. Real GPT-5 generation, narration, native Manim rendering and three visual-review/repair rounds executed. The video did not pass: remaining annotation collisions caused strict stage 3 to block the bundle. This is a failed quality reproduction, not a successful delivered lesson. No unreviewed-bundle override was used. Browser clicks verified that wrong choices keep Continue locked and a correct choice unlocks it, without page errors. The planner nevertheless requested a Check button that the auto-grading template does not provide; one later visual review misidentified the CHECK badge as that button. Screenshot review cannot establish interactive correctness.

An interrupted run also exposed cached Manim recovery with no in-memory prior (`None.model_copy`). A minimal initialization fix is covered by a regression that fails on the original code and passes on the fix; 47 selected regression tests passed in the fresh environment. This correction does not resolve the independent visual-generation or planner/template issues. See `evidence/fresh-environment-verification.json` for scores, failure reasons and scope.
