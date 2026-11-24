# EduCAST minimal reproducibility release

Baseline: DaRL-GenAI/EduCAST commit `539a045bfde7986d28d0bc932959d2615ce5abf0`, source subtree `src/eduharness`.
The original source is preserved; production changes are limited to four Python files. See `source.patch` and `source-manifest.json` for exact provenance.

## Changes

1. Respect `enable_remotion=false` when shaping the lesson opener. Previously the last sanitizer step silently converted the first teaching scene into Remotion and replaced its teaching requirements.
2. Skip inaccessible individual media-tool candidates instead of aborting PATH resolution.
3. Consume discarded FFmpeg output through subprocess pipes, supporting hosts where `/dev/null` cannot be opened for writing. Remotion uses `run(check=True)`, which drains these pipes.

No model prompts, review criteria, pass thresholds, repair budgets or strict bundle rules were relaxed. The sample is a small Manim lesson plus an interactive question; the planner remains model driven.

## Install and run on a normal Linux host

Use Python 3.10 or later. Manim needs Cairo/Pango development libraries and a compiler if wheels are unavailable; install these using your system's approved method. FFmpeg and FFprobe must be executable. Keep all virtualenvs, downloads and browser caches in your own working directory.

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

`requirements-observed.txt` records the important versions used in this audit; it is an observed configuration, not a full platform lock. Core API dependencies were freshly installed; the existing Manim/Playwright installation was reused and tested with real subprocesses. A fully clean installation of the entire rendering toolchain was not verified.

## Resuming without regenerating the lesson

The CLI supports `--stage 2-render --force --no-repair`, `--stage 2-review`, and `--stage 3`. Use the same request and run directory for all stages. After a cached `review_error`, explicitly rerun `--stage 2-review`; do not assume a full pipeline invocation retries cached review errors.

Never enable `allow_unreviewed_bundle` to claim successful reproduction. Check `rendered_scenes.json`: `ffmpeg-slide-fallback` and `manim-safe-fallback` do not demonstrate native renderer success. Declare any `manim-no-latex` downgrade. A real initial PASS does not prove the repair path actually ran.

## Restricted environment adapter

`scripts/node_stdio_pipe.cjs` is optional and is NOT loaded by default. On hosts where Node cannot use `/dev/null`, enable it with `NODE_OPTIONS="--require=$PWD/scripts/node_stdio_pipe.cjs"`. It changes only explicit array `ignore` entries of three-argument `child_process.spawn` into drained pipes. It is not a general Node compatibility patch. Chromium itself may additionally require `--no-zygote --single-process` in a local executable wrapper. These are environment adaptations, not model changes; the filesystem guard must remain active.

See `evidence/verification.json` for actual tested branches and limitations. Offline FakeProvider checks are never counted as real API generation or real vision review.

## Verified result

Real API generation produced native Manim video, narration, and a template-based interactive question. Actual visual reviews passed at 8.5 and 9.5; strict stage 3 produced the player and manifest with unreviewed output disabled. The source repair path fixed a renderer exception and regenerated after seven layout findings, ending with zero findings. Review was resumed explicitly after the host browser adaptation. Nine API calls were recorded (including two vision reviews); the usage estimate was $0.5181. Interactive clicking, image generation, and native Remotion were not validated.

On this write-restricted audit host, third-party Manim also needed a task-local output sink instead of `/dev/null`. That regular file is not semantically identical to the null device and is a host-only adaptation, not a required source change.

## Review follow-up fixes

The real API evidence above describes the preceding reproducibility run, not a quality validation of these follow-up changes. Offline regression tests now exercise reject -> feedback to generation -> render -> re-review, and recovery from a cached reviewer outage without regenerating or consuming a generation attempt.

Video evidence scales with duration (roughly one sample per two seconds, up to 16 base samples by default), plus Manim boundary frames. Explicit higher frame settings, Remotion extras and layout-guard timestamps remain respected. This is still sampled visual review, not continuous video/audio inspection or automated interaction testing. The reviewer must check requested visual demonstrations and cannot infer click behavior from a screenshot. Pass thresholds and generation budgets are unchanged.

Resuming a run now retries cached review errors automatically. Use the latest `rendered_scenes.json` as the verdict; old HITL text files can remain from an earlier outage. The existing preview/demo is the earlier run and was not regenerated by these follow-up changes.

First-scene title-card treatment is now limited to Remotion; a first Manim teaching scene receives the teaching-board review contract. Resumed repair also applies a requested tool change before preparing its next attempt.
