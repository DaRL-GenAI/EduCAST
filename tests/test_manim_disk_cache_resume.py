"""A disk spec can survive an interrupted run without an in-memory prior."""
import json
from educast.schema import SceneBrief, SceneType, StyleConfig
from educast.reviewloop import repair_router


def test_disk_manim_spec_reused_without_prior_or_api(tmp_path):
    scene = SceneBrief(id="area", title="Area", scene_type=SceneType.MANIM, visual_brief="Show rectangle area")
    work = tmp_path / "work" / scene.id
    work.mkdir(parents=True)
    payload = {"construct_body": "self.wait(1)", "scene_class_name": "EduScene"}
    (work / "manim_spec.json").write_text(json.dumps(payload))
    class NoAPI:
        def __getattr__(self, name):
            raise AssertionError("disk cache must not call API: " + name)
    prepared = repair_router.prepare_with_repair(
        provider=NoAPI(), scene=scene, style=StyleConfig(), work=work,
        run_dir=tmp_path, prior=None, repair=None, attempt=0,
        narration_seconds=None,
    )
    assert prepared.scene_id == scene.id
    assert prepared.scene_type == SceneType.MANIM
    assert prepared.attempt == 0
    assert prepared.debug["repair_mode"] == "prior_reused"
    assert json.loads((tmp_path / prepared.spec_path).read_text()) == payload
