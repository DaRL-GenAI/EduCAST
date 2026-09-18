from __future__ import annotations

import json

import pytest

from eduharness.schema import (
    LessonBlueprint,
    Manifest,
    RenderedScene,
    SceneBrief,
    SceneType,
)
from eduharness.stage3.bundler import build_bundle


def _blueprint() -> LessonBlueprint:
    return LessonBlueprint(
        topic='<img src=x onerror="alert(1)">',
        audience="students",
        learning_goal="test",
        scenes=[
            SceneBrief(
                id="video",
                title="Video",
                scene_type=SceneType.MANIM,
                visual_brief="A video",
                target_seconds=10,
            ),
            SceneBrief(
                id="overlay",
                title="Checkpoint",
                scene_type=SceneType.INTERACTIVE,
                visual_brief="Question",
                template="multiple_choice",
                trigger_scene_id="video",
                trigger_at_seconds=4,
            ),
        ],
    )


def _rendered(review_passed: bool = True) -> list[RenderedScene]:
    return [
        RenderedScene(
            scene_id="video",
            scene_type=SceneType.MANIM,
            src="media/video.mp4",
            duration=10,
            review_passed=review_passed,
        ),
        RenderedScene(
            scene_id="overlay",
            scene_type=SceneType.INTERACTIVE,
            src="interactive/overlay.json",
            template="multiple_choice",
            review_passed=review_passed,
        ),
    ]


def _artifacts(run_dir) -> None:
    (run_dir / "media").mkdir(parents=True)
    (run_dir / "interactive").mkdir()
    (run_dir / "media" / "video.mp4").write_bytes(b"video")
    (run_dir / "interactive" / "overlay.json").write_text(
        json.dumps(
            {
                "template": "multiple_choice",
                "parameters": {
                    "question": "Q",
                    "choices": ["A", "B"],
                    "correct_index": 0,
                },
            }
        ),
        encoding="utf-8",
    )


def test_strict_bundle_rejects_unreviewed_assets(tmp_path) -> None:
    _artifacts(tmp_path)
    with pytest.raises(RuntimeError, match="quality gate"):
        build_bundle(tmp_path, _blueprint(), _rendered(False), "test")


def test_allow_unreviewed_bundle_writes_warnings(tmp_path) -> None:
    _artifacts(tmp_path)
    manifest = build_bundle(
        tmp_path, _blueprint(), _rendered(False), "test", allow_unreviewed=True
    )
    assert manifest.bundle_id == "test"
    warnings = json.loads((tmp_path / "bundle" / "warnings.json").read_text())
    assert warnings["allow_unreviewed"] is True
    assert any("review did not pass" in item for item in warnings["problems"])


def _bundle_bytes(run_dir) -> dict[str, bytes]:
    bundle = run_dir / "bundle"
    return {
        path.relative_to(bundle).as_posix(): path.read_bytes()
        for path in bundle.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize("allow_unreviewed", [False, True])
@pytest.mark.parametrize("scene_index", [0, 1], ids=["video", "overlay"])
@pytest.mark.parametrize("failure", ["missing_result", "empty_source", "missing_file"])
def test_incomplete_render_preserves_published_bundle(
    tmp_path, allow_unreviewed, scene_index, failure
) -> None:
    _artifacts(tmp_path)
    build_bundle(tmp_path, _blueprint(), _rendered(), "published")
    published = _bundle_bytes(tmp_path)
    # A successful early scene must not overwrite the published version if a
    # later scene failed, including the unreviewed rows produced by render errors.
    (tmp_path / "media/video.mp4").write_bytes(b"newly rendered video")
    rendered = _rendered(False)
    result = rendered[scene_index]
    if failure == "missing_result":
        rendered.remove(result)
        message = "no rendered result"
    elif failure == "empty_source":
        result.src = ""
        message = "no rendered source"
    else:
        (tmp_path / result.src).unlink()
        message = "source file missing"

    with pytest.raises(RuntimeError, match=f"{result.scene_id}: {message}"):
        build_bundle(
            tmp_path, _blueprint(), rendered, "replacement",
            allow_unreviewed=allow_unreviewed,
        )
    assert _bundle_bytes(tmp_path) == published


@pytest.mark.parametrize(
    ("defect", "message"),
    [
        ("empty_blueprint", "blueprint has no scenes"),
        ("duplicate_blueprint", "duplicate blueprint scene ID"),
        ("duplicate_rendered", "duplicate rendered scene ID"),
        ("wrong_type", "does not match blueprint type"),
        ("missing_target", "must be an earlier video scene"),
        ("later_target", "must be an earlier video scene"),
        ("image_target", "must be an earlier video scene"),
        ("late_trigger", "is outside video duration"),
        ("infinite_trigger", "must be finite and nonnegative"),
        ("orphan_trigger", "requires an overlay target"),
    ],
)
def test_review_override_cannot_publish_broken_timeline(tmp_path, defect, message) -> None:
    _artifacts(tmp_path)
    build_bundle(tmp_path, _blueprint(), _rendered(), "published")
    published = _bundle_bytes(tmp_path)
    (tmp_path / "media/video.mp4").write_bytes(b"newly rendered video")
    blueprint, rendered = _blueprint(), _rendered()
    if defect == "empty_blueprint":
        blueprint.scenes = []
    elif defect == "duplicate_blueprint":
        blueprint.scenes.append(blueprint.scenes[0].model_copy())
    elif defect == "duplicate_rendered":
        rendered.append(rendered[0].model_copy())
    elif defect == "wrong_type":
        rendered[0].scene_type = SceneType.IMAGE
    elif defect == "missing_target":
        blueprint.scenes[1].trigger_scene_id = "missing"
    elif defect == "later_target":
        blueprint.scenes.reverse()
    elif defect == "image_target":
        blueprint.scenes[0].scene_type = rendered[0].scene_type = SceneType.IMAGE
    elif defect == "late_trigger":
        blueprint.scenes[1].trigger_at_seconds = 10
    elif defect == "infinite_trigger":
        blueprint.scenes[1].trigger_at_seconds = float("inf")
    elif defect == "orphan_trigger":
        blueprint.scenes[1].trigger_scene_id = None

    with pytest.raises(RuntimeError, match=message):
        build_bundle(tmp_path, blueprint, rendered, "replacement", allow_unreviewed=True)
    assert _bundle_bytes(tmp_path) == published


def test_reviewed_rebuild_clears_old_warnings(tmp_path) -> None:
    _artifacts(tmp_path)
    build_bundle(tmp_path, _blueprint(), _rendered(False), "test", allow_unreviewed=True)
    build_bundle(tmp_path, _blueprint(), _rendered(), "test")
    assert not (tmp_path / "bundle/warnings.json").exists()


def test_video_overlay_and_safe_html_are_generated(tmp_path) -> None:
    _artifacts(tmp_path)
    manifest = build_bundle(tmp_path, _blueprint(), _rendered(), "test")
    assert len(manifest.timeline) == 1
    assert manifest.timeline[0].overlays[0].trigger_at == 4
    html = (tmp_path / "bundle" / "index.html").read_text(encoding="utf-8")
    assert '<img src=x onerror="alert(1)">' not in html
    assert "&lt;img" in html
    player = (tmp_path / "bundle" / "player.js").read_text(encoding="utf-8")
    assert "INTERACTIVE_PAUSE" in player
    assert "clearTimeout" in player


def test_legacy_manifest_without_overlays_still_loads() -> None:
    manifest = Manifest.model_validate(
        {
            "bundle_id": "legacy",
            "topic": "Legacy",
            "style": {},
            "timeline": [
                {"id": "one", "type": "image", "src": "media/one.png", "duration": 3}
            ],
        }
    )
    assert manifest.timeline[0].overlays == []
