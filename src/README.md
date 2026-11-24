# EduCAST source

The current implementation is **[`eduharness/`](eduharness/README.md)**.
It includes planning, native rendering, narration, scene-level review and repair,
interactive lessons, the bundle player, and the GUI backend.

| Path | Purpose |
| --- | --- |
| [`eduharness/`](eduharness/README.md) | Current system, installation, CLI examples, and tests |
| [`eduharness/docs/pipeline.md`](eduharness/docs/pipeline.md) | Pipeline and review/repair details |
| `baseline/` | Colab comparison runners; require external upstream projects and the documented Drive layout |
| `notebooks/eval.ipynb` | Historical evaluation notebook; requires external `Teaching_Video_Generation` with `teachgen.eval` (not included) |
| `baseline/api_usage_tracker.py` | API usage and cost tracking for baseline notebook runs |
| `topics.xlsx`, `data/` | Topic set and structured-request summaries |

For local generation, follow the [current system setup](eduharness/README.md),
then run `examples/minimal_request.json` from `eduharness/`.
Generated lessons, local environments, and verification outputs are not versioned.
