# EduCAST source

The current implementation is **[`eduharness/`](eduharness/README.md)**.
It includes planning, native rendering, narration, scene-level review and repair,
interactive lessons, the bundle player, and the GUI backend.

| Path | Purpose |
| --- | --- |
| [`eduharness/`](eduharness/README.md) | Current system, installation, CLI examples, and tests |
| [`eduharness/docs/pipeline.md`](eduharness/docs/pipeline.md) | Pipeline and review/repair details |
| [`legacy/`](legacy/README.md) | Original `teachgen` pipeline and its evaluator |
| `baseline/` | Colab runners for Code2Video, Manim, Remotion, and TeachingMonster |
| `notebooks/` | Pipeline, website, and video-evaluation notebooks |
| `tools/api_usage_tracker.py` | API usage and cost tracking for notebook runs |
| `topics.xlsx`, `data/` | Topic set and structured-request summaries |

For local generation, follow the [current system setup](eduharness/README.md),
then run `examples/minimal_request.json` from `eduharness/`.
Generated lessons, local environments, and verification outputs are not versioned.
