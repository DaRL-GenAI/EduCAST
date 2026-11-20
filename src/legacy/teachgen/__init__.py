"""teachgen — one-key, one-topic teaching-video generator.

Phase 1 (text only): topic -> teaching content -> LessonPlan (per-segment route).
Phase 2 (media):      narrate + render each segment -> composite -> MLLM review loop.

The three production paths (code2video animation, pptx slide, concept image) are
plugged in as *segment-level renderers* behind a common interface, so adding a
fourth path means writing one plugin, not touching the pipeline.
"""

__version__ = "0.1.0"
