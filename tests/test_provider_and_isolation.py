"""Provider budget escalation helpers + per-scene failure isolation in prepare_all."""

from __future__ import annotations

from eduharness.config import Config
from eduharness.providers.openai_provider import _lower_effort, _strip_fences
from eduharness.schema import HarnessRequest, LessonBlueprint, SceneBrief, SceneType
from eduharness.stage2 import workflow
from tests.conftest import FakeProvider


def test_lower_effort_steps_down_and_saturates() -> None:
    assert _lower_effort("high") == "medium"
    assert _lower_effort("medium") == "low"
    assert _lower_effort("minimal") == "minimal"
    assert _lower_effort(None) is None


def test_strip_fences_handles_json_fence() -> None:
    assert _strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert _strip_fences('{"a": 1}') == '{"a": 1}'


def test_prepare_failure_is_isolated_and_reported(tmp_path, ffmpeg) -> None:
    cfg = Config(request=HarnessRequest(request_id="iso", topic="T", enable_narration=False), run_dir=tmp_path)
    cfg.ensure_dirs()
    blueprint = LessonBlueprint(
        topic="T", audience="a", learning_goal="g",
        scenes=[
            SceneBrief(id="img", title="I", scene_type=SceneType.IMAGE, visual_brief="x", key_elements=["x"]),
            SceneBrief(id="anim", title="A", scene_type=SceneType.MANIM, visual_brief="y", key_elements=["y"]),
        ],
    )

    class Exploding(FakeProvider):
        def chat_json(self, prompt, schema, **kwargs):
            if "construct_body" in schema.model_fields:
                raise RuntimeError("model returned nothing")
            return super().chat_json(prompt, schema, **kwargs)

    provider = Exploding()
    prepared = workflow.prepare_all(cfg, provider, blueprint)
    assert prepared[0].asset_path  # the image scene still completed
    assert prepared[1].debug["prepare_error"].startswith("model returned nothing")
    rendered = workflow.render_all(cfg, blueprint, prepared)
    assert rendered[0].src and not rendered[1].src
    reviewed = workflow.review_all(cfg, provider, blueprint, rendered)
    assert reviewed[0].review_passed
    assert not reviewed[1].review_passed and not reviewed[1].review_error
    assert reviewed[1].repair.needs_repair()  # next round re-prepares only this scene


def test_force_render_redoes_every_scene_and_drops_stale_verdicts(tmp_path, ffmpeg) -> None:
    """A style-board change must not inherit an audit of the previous look."""
    from eduharness.pipeline import stage2_render
    from eduharness.schema import SceneBrief, SceneType

    cfg = Config(request=HarnessRequest(request_id="force", topic="T", enable_narration=False),
                 run_dir=tmp_path)
    cfg.ensure_dirs()
    blueprint = LessonBlueprint(
        topic="T", audience="a", learning_goal="g",
        scenes=[SceneBrief(id="img", title="I", scene_type=SceneType.IMAGE,
                           visual_brief="x", key_elements=["x"])],
    )
    cfg.blueprint_path.write_text(blueprint.model_dump_json(indent=2), encoding="utf-8")
    provider = FakeProvider()
    prepared = workflow.prepare_all(cfg, provider, blueprint)
    rendered = workflow.render_all(cfg, blueprint, prepared)
    reviewed = workflow.review_all(cfg, provider, blueprint, rendered)
    assert reviewed[0].review_passed

    again = stage2_render(cfg, blueprint)
    assert again[0].review_passed

    forced = stage2_render(cfg, blueprint, force=True)
    assert not forced[0].review_passed, "a forced re-render must require a fresh audit"
    assert forced[0].src == "media/img.png"
