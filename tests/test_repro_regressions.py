"""Regression checks for the minimal reproducibility fixes."""
from pathlib import Path
import subprocess
from educast.schema import HarnessRequest, SceneBrief, SceneType, LessonBlueprint
from educast.agents.planner import _sanitize
from educast import media


def test_disabled_remotion_does_not_overwrite_first_teaching_scene():
    scene = SceneBrief(id="worked", title="Torque", scene_type=SceneType.MANIM,
                       visual_brief="Draw a lever", key_elements=["lever", "force arrows"])
    bp = LessonBlueprint(topic="Torque", audience="students", learning_goal="Balance a lever", scenes=[scene])
    result = _sanitize(bp, HarnessRequest(topic="Torque", enable_remotion=False))
    assert result.scenes[0].scene_type == SceneType.MANIM
    assert result.scenes[0].key_elements == ["lever", "force arrows"]
    assert result.scenes[0].visual_brief == "Draw a lever"


def test_enabled_remotion_retains_original_opener():
    scene = SceneBrief(id="opening", title="Torque", scene_type=SceneType.REMOTION, visual_brief="Title")
    bp = LessonBlueprint(topic="Torque", audience="students", learning_goal="Balance a lever", scenes=[scene])
    result = _sanitize(bp, HarnessRequest(topic="Torque", enable_remotion=True))
    assert result.scenes[0].scene_type == SceneType.REMOTION
    assert result.scenes[0].key_elements == ["Lesson title: Torque"]


def test_inaccessible_path_does_not_hide_explicit_media_tool(monkeypatch):
    real_is_file = Path.is_file
    def checked_is_file(path):
        if str(path).startswith("/inaccessible-repro-test/"):
            raise PermissionError("unreadable PATH entry")
        return real_is_file(path)
    monkeypatch.setattr(Path, "is_file", checked_is_file)
    monkeypatch.setenv("PATH", "/inaccessible-repro-test")
    monkeypatch.setenv("EDUHARNESS_FFMPEG", "/chosen/ffmpeg")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 0))
    monkeypatch.setattr(media, "_TOOL_CACHE", {})
    assert media.ffmpeg_bin() == "/chosen/ffmpeg"
