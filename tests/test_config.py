from __future__ import annotations

import os
from pathlib import Path

from eduharness.config import Config
from eduharness.schema import HarnessRequest


def test_dotenv_loads_api_key(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=from-dotenv\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    request = HarnessRequest(request_id="dotenv", topic="T")
    cfg = Config.from_env(request, run_dir=tmp_path / "run")
    assert cfg.api_key == "from-dotenv"


def test_split_text_and_media_endpoints(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("eduharness.config.load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("EDUHARNESS_TEXT_BASE_URL", "http://relay.local/v1")
    monkeypatch.setenv("EDUHARNESS_TEXT_API_KEY", "relay-key")
    monkeypatch.delenv("EDUHARNESS_MEDIA_API_KEY", raising=False)
    request = HarnessRequest(request_id="relay", topic="T", enable_image=True, enable_narration=True)
    cfg = Config.from_env(request, run_dir=tmp_path / "run")
    assert cfg.api_key == "relay-key"
    assert cfg.models.text_base_url == "http://relay.local/v1"
    # no media key anywhere → image scenes and narration are switched off, not crashed
    assert cfg.enable_image is False and cfg.enable_narration is False
    monkeypatch.setenv("EDUHARNESS_MEDIA_API_KEY", "official-key")
    cfg2 = Config.from_env(request, run_dir=tmp_path / "run2")
    assert cfg2.enable_image and cfg2.enable_narration and cfg2.models.media_api_key == "official-key"


def test_animation_steps_are_paired_with_lecture_lines() -> None:
    """One step per line, in order: a longer plan is trimmed and a short one padded,
    so the renderer prompt can pair step N with line N without dropping a line."""
    from eduharness.schema import SceneBrief, SceneType
    from eduharness.stage1.main_agent import _align_animation_steps

    long_plan = SceneBrief(
        id="s", title="T", scene_type=SceneType.MANIM, visual_brief="v",
        lecture_lines=["one", "two"],
        animations=["arrow slides", "box flashes", "extra step nobody reads"],
    )
    _align_animation_steps(long_plan)
    assert long_plan.animations == ["arrow slides", "box flashes"]

    short_plan = SceneBrief(
        id="s", title="T", scene_type=SceneType.MANIM, visual_brief="v",
        lecture_lines=["one", "two", "three"], animations=["arrow slides"],
    )
    _align_animation_steps(short_plan)
    assert len(short_plan.animations) == 3
    assert short_plan.animations[0] == "arrow slides"
    assert "two" in short_plan.animations[1] and "three" in short_plan.animations[2]

    still = SceneBrief(id="s", title="T", scene_type=SceneType.IMAGE, visual_brief="v",
                       lecture_lines=["one"], animations=["nothing moves in a still"])
    _align_animation_steps(still)
    assert still.animations == []


def test_key_scenes_are_capped_and_budget_lecture_lines() -> None:
    """Three scenes at most carry the five-line budget; the rest fall back to three,
    so a plan cannot make every scene equally shallow by marking them all key."""
    from eduharness.schema import LessonBlueprint, SceneBrief, SceneType, StyleConfig
    from eduharness.stage1.main_agent import _align_animation_steps, _cap_key_scenes

    def scene(index: int) -> SceneBrief:
        return SceneBrief(
            id=f"s{index}", title=f"T{index}", scene_type=SceneType.MANIM, visual_brief="v",
            key_scene=True,
            lecture_lines=[f"line {i}" for i in range(5)],
            animations=[f"step {i}" for i in range(5)],
        )

    plan = LessonBlueprint(topic="t", audience="a", learning_goal="g",
                           style=StyleConfig(), scenes=[scene(i) for i in range(5)])
    _cap_key_scenes(plan)
    assert [s.key_scene for s in plan.scenes] == [True, True, True, False, False]
    assert [len(s.animations) for s in plan.scenes] == [5, 5, 5, 3, 3]
    assert [len(s.lecture_lines) for s in plan.scenes] == [5, 5, 5, 3, 3]

    demoted = plan.scenes[-1]
    _align_animation_steps(demoted)
    assert len(demoted.animations) == 3


def test_layout_contract_pins_the_row_stack() -> None:
    from eduharness.schema import StyleConfig, layout_contract

    text = layout_contract(StyleConfig())
    # The drawing owns the stage; only loose text stacks into rows. Getting this
    # backwards planned a scene as six rows of text and dropped the circuit.
    assert "THE DRAWING COMES FIRST" in text and "A1-D6 is the drawing area" in text
    assert "LOOSE TEXT IS STACKED IN ROWS" in text and "reading order" in text
    assert text.index("THE DRAWING COMES FIRST") < text.index("LOOSE TEXT IS STACKED IN ROWS")
