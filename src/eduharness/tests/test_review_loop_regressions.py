"""Offline control-flow tests; these do not claim real model quality improvement."""
import pytest

from eduharness.config import Config
from eduharness.schema import HarnessRequest, RenderedScene, SceneBrief, SceneType
from eduharness.stage2 import workflow
from tests.conftest import FakeProvider
from tests.test_workflow_security import _image_blueprint


def test_rejected_scene_receives_feedback_and_is_reviewed_again(tmp_path, ffmpeg):
    issue = "Diagram omits the lever pivot; draw the pivot."

    class RejectThenPass(FakeProvider):
        def __init__(self):
            super().__init__()
            self.reviews = 0
            self.prompts = []

        def chat(self, prompt, **kwargs):
            self.prompts.append(prompt)
            return super().chat(prompt, **kwargs)

        def vision_json(self, prompt, image_paths, schema, **kwargs):
            self.reviews += 1
            self.verdict = ({"score": 4, "brief_adherence": 4,
                             "blocking_issues": [issue], "fix_action": "re_render"}
                            if self.reviews == 1 else {"score": 9, "brief_adherence": 9})
            return super().vision_json(prompt, image_paths, schema, **kwargs)

    cfg = Config(request=HarnessRequest(request_id="loop", topic="T", max_review_rounds=2), run_dir=tmp_path)
    cfg.ensure_dirs()
    provider = RejectThenPass()
    result = workflow.run_repair_loop(cfg, provider, _image_blueprint())
    assert result[0].review_passed
    assert provider.reviews == 2
    assert provider.calls.count("image") == 2
    assert provider.tts_calls == 1
    assert issue in provider.prompts[-1]
    assert workflow.load_prepared(cfg)[0].attempt == 1


def test_resume_retries_review_outage_without_regenerating(tmp_path, ffmpeg):
    class Outage(FakeProvider):
        def vision_json(self, *args, **kwargs):
            raise RuntimeError("temporary review outage")

    cfg = Config(request=HarnessRequest(request_id="resume", topic="T", max_review_rounds=2), run_dir=tmp_path)
    cfg.ensure_dirs()
    blueprint = _image_blueprint()
    assert workflow.run_repair_loop(cfg, Outage(), blueprint)[0].review_error
    recovered = FakeProvider()
    result = workflow.run_repair_loop(cfg, recovered, blueprint)
    assert result[0].review_passed and not result[0].review_error
    assert recovered.calls == ["vision_json:_ReviewOut"]
    assert workflow.load_prepared(cfg)[0].attempt == 0


@pytest.mark.parametrize("duration, minimum", [(24, 12), (120, 16)])
def test_video_review_uses_bounded_temporal_coverage(tmp_path, monkeypatch, duration, minimum):
    cfg = Config(request=HarnessRequest(request_id="frames", topic="T"), run_dir=tmp_path)
    video = tmp_path / "video.mp4"
    video.touch()
    captured = {}

    def extract(*args, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(workflow.media, "extract_video_frames", extract)
    scene = SceneBrief(id="s", title="S", scene_type=SceneType.MANIM, visual_brief="Show torque")
    rendered = RenderedScene(scene_id="s", scene_type=SceneType.MANIM, src="video.mp4", visual_seconds=duration)
    workflow.preview_frames(cfg, rendered, scene)
    assert captured["count"] == minimum
    assert captured["extra_seconds"] == [0.25, duration - 0.25]


@pytest.mark.parametrize("kind", [SceneType.MANIM, SceneType.REMOTION])
def test_first_teaching_scene_is_not_reviewed_as_title_card(tmp_path, monkeypatch, kind):
    from eduharness.stage2.media import Frame

    class Capture(FakeProvider):
        prompt = ""

        def vision_json(self, prompt, *args, **kwargs):
            self.prompt = prompt
            return super().vision_json(prompt, *args, **kwargs)

    cfg = Config(request=HarnessRequest(request_id="contract", topic="T"), run_dir=tmp_path)
    cfg.ensure_dirs()
    blueprint = _image_blueprint()
    blueprint.scenes[0].scene_type = kind
    scene = blueprint.scenes[0]
    result = RenderedScene(scene_id=scene.id, scene_type=kind, src="video.mp4")
    monkeypatch.setattr(workflow, "preview_frames", lambda *a: ([Frame(path=tmp_path / "frame.jpg", seconds=1, label="uniform")], []))
    monkeypatch.setattr(workflow.media, "blank_frame_findings", lambda *a: [])
    provider = Capture()
    workflow._review_one(cfg, provider, blueprint, scene, result, None)
    assert ("Lesson opener on its own stage" in provider.prompt) == (kind == SceneType.REMOTION)
    if kind == SceneType.MANIM:
        assert "PLANNED ELEMENT PLACEMENTS" in provider.prompt


def test_resume_applies_requested_tool_change_before_preparation(tmp_path, ffmpeg, monkeypatch):
    class Outage(FakeProvider):
        def vision_json(self, *args, **kwargs):
            raise RuntimeError("temporary review outage")

    cfg = Config(request=HarnessRequest(request_id="tool", topic="T", enable_manim=True), run_dir=tmp_path)
    cfg.ensure_dirs()
    blueprint = _image_blueprint()
    assert workflow.run_repair_loop(cfg, Outage(), blueprint)[0].review_error
    recovered = FakeProvider(verdict={"score": 4, "brief_adherence": 4,
                                     "blocking_issues": ["A still cannot demonstrate the requested movement."],
                                     "fix_action": "change_tool"})

    class PreparationReached(Exception):
        pass

    def prepare(cfg, provider, blueprint, **kwargs):
        assert blueprint.scenes[0].scene_type == SceneType.MANIM
        repair = kwargs["repairs_by_id"]["image"]
        assert repair.scene_type == SceneType.MANIM
        assert repair.fix_action == "re_render"
        raise PreparationReached

    monkeypatch.setattr(workflow, "prepare_all", prepare)
    with pytest.raises(PreparationReached):
        workflow.run_repair_loop(cfg, recovered, blueprint)


@pytest.mark.parametrize("force, expected_calls", [(False, 0), (True, 1)])
def test_explicit_review_force_reaudits_passed_output(tmp_path, monkeypatch, force, expected_calls):
    from eduharness import pipeline
    from eduharness.stage2.media import Frame

    cfg = Config(request=HarnessRequest(request_id="reaudit", topic="T"), run_dir=tmp_path)
    cfg.ensure_dirs()
    blueprint = _image_blueprint()
    result = RenderedScene(scene_id="image", scene_type=SceneType.IMAGE,
                           src="image.png", review_passed=True)
    cfg.rendered_path.write_text("[" + result.model_dump_json() + "]")
    monkeypatch.setattr(workflow, "preview_frames", lambda *a: ([Frame(path=tmp_path / "frame.jpg", seconds=0, label="still")], []))
    provider = FakeProvider()
    pipeline.stage2_review(cfg, provider, blueprint, force=force)
    assert provider.calls.count("vision_json:_ReviewOut") == expected_calls


def test_force_review_revokes_old_pass_and_blocks_bundle(tmp_path, monkeypatch):
    from eduharness import pipeline
    from eduharness.stage2.media import Frame

    cfg = Config(request=HarnessRequest(request_id="revoke", topic="T"), run_dir=tmp_path)
    cfg.ensure_dirs()
    from PIL import Image
    Image.new("RGB", (64, 64), "white").save(tmp_path / "image.png")
    blueprint = _image_blueprint()
    result = RenderedScene(scene_id="image", scene_type=SceneType.IMAGE, src="image.png", review_passed=True)
    cfg.rendered_path.write_text("[" + result.model_dump_json() + "]")
    monkeypatch.setattr(workflow, "preview_frames", lambda *a: ([Frame(path=tmp_path / "frame.jpg", seconds=0, label="still")], []))
    provider = FakeProvider(verdict={"score": 4, "brief_adherence": 4, "blocking_issues": ["Required diagram is missing."]})
    pipeline.stage2_review(cfg, provider, blueprint, force=True)
    assert not workflow.load_rendered(cfg)[0].review_passed
    with pytest.raises(RuntimeError, match="quality gate"):
        pipeline.stage3(cfg, blueprint)
