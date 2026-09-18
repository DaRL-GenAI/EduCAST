from __future__ import annotations

from PIL import Image
import pytest

from eduharness.config import Config
from eduharness.schema import (
    HarnessRequest,
    LessonBlueprint,
    SceneBrief,
    SceneType,
)
from eduharness.stage2 import workflow
from eduharness.stage2 import reviewer
from eduharness.stage2.adapters.manim import (
    sanitize_construct_body,
    validate_construct_body,
)
from tests.conftest import FakeProvider


def _image_blueprint() -> LessonBlueprint:
    return LessonBlueprint(
        topic="T",
        audience="students",
        learning_goal="learn",
        scenes=[
            SceneBrief(
                id="image",
                title="Image",
                narration="A short narration.",
                scene_type=SceneType.IMAGE,
                visual_brief="A diagram",
                caption="A caption drawn by the adapter",
                key_elements=["a diagram"],
            )
        ],
    )


def test_checkpointed_image_workflow_without_real_api(tmp_path, ffmpeg) -> None:
    request = HarnessRequest(request_id="test", topic="T")
    cfg = Config(request=request, run_dir=tmp_path)
    cfg.ensure_dirs()
    blueprint = _image_blueprint()
    provider = FakeProvider()
    prepared = workflow.prepare_all(cfg, provider, blueprint)
    assert provider.calls.index("chat") < provider.calls.index("image")
    assert prepared[0].debug["image_render_mode"] == "concept_image"
    assert (tmp_path / "work/image/image_prompt.txt").read_text() == "ok"
    assert prepared[0].narration_path and (tmp_path / prepared[0].narration_path).is_file()
    rendered = workflow.render_all(cfg, blueprint, prepared)
    assert rendered[0].render_mode == "concept-image"
    reviewed = workflow.review_all(cfg, provider, blueprint, rendered)
    assert reviewed[0].review_passed
    assert reviewed[0].repair is not None
    assert reviewed[0].repair.fix_action == "noop"
    assert reviewed[0].audio_src == "media/image.mp3"
    assert reviewed[0].duration and reviewed[0].duration >= 8.0
    assert Image.open(tmp_path / "media" / "image.png").size == (1920, 1080)
    # narration is cached across repair rounds
    workflow.prepare_all(cfg, provider, blueprint, previous=prepared, only_scene_ids={"image"},
                         feedback_by_id={"image": "make it bigger"})
    assert provider.tts_calls == 1


def test_missing_key_element_fails_review(tmp_path, ffmpeg) -> None:
    request = HarnessRequest(request_id="test", topic="T")
    cfg = Config(request=request, run_dir=tmp_path)
    cfg.ensure_dirs()
    blueprint = _image_blueprint()
    provider = FakeProvider(verdict={
        "score": 8, "brief_adherence": 4, "missing_key_elements": ["a diagram"],
        "fix_action": "re_render", "fallback_instructions": "draw the diagram",
    })
    prepared = workflow.prepare_all(cfg, provider, blueprint)
    rendered = workflow.render_all(cfg, blueprint, prepared)
    reviewed = workflow.review_all(cfg, provider, blueprint, rendered)
    assert not reviewed[0].review_passed
    assert reviewed[0].repair.needs_repair()
    assert "Missing key element: a diagram" in reviewed[0].repair.blocking_issues
    assert reviewed[0].repair.severity == "blocker"


def test_stage3_config_does_not_require_api_key(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("eduharness.config.load_dotenv", lambda *a, **k: False)
    request = HarnessRequest(request_id="offline", topic="T")
    cfg = Config.from_env(request, run_dir=tmp_path, require_api_key=False)
    assert cfg.api_key == ""


@pytest.mark.parametrize(
    "body",
    [
        "import os\nself.wait(1)",
        "open('/tmp/x', 'w')",
        "self.__class__",
        "__import__('subprocess')",
        "getattr(self, 'renderer')",
        "class X: pass",
    ],
)
def test_manim_ast_rejects_unsafe_code(body: str) -> None:
    with pytest.raises(ValueError, match="Forbidden"):
        validate_construct_body(body)


def test_manim_ast_allows_normal_scene_body() -> None:
    validate_construct_body(
        "title = Text('Safe', color=TEXT_COLOR)\n"
        "self.play(Write(title))\n"
        "self.wait(0.5)"
    )


def test_sanitize_strips_manim_imports_and_class_wrappers() -> None:
    body = sanitize_construct_body(
        "from manim import *\n"
        "import math\n"
        "title = Text('Hi', color=TEXT_COLOR)\n"
        "self.play(Write(title))\n"
    )
    assert "from manim" not in body
    assert "import math" not in body
    validate_construct_body(body)
    assert "Text('Hi'" in body

    wrapped = sanitize_construct_body(
        "class EduScene(Scene):\n"
        "    def construct(self):\n"
        "        t = Text('x')\n"
        "        self.play(Write(t))\n"
    )
    assert wrapped.startswith("t = Text('x')")
    validate_construct_body(wrapped)


def test_reviewer_api_failure_is_fail_closed(tmp_path) -> None:
    image = tmp_path / "frame.png"
    Image.new("RGB", (20, 20), "black").save(image)

    class BrokenProvider:
        def vision(self, *args, **kwargs):
            raise RuntimeError("network unavailable")

        def chat_json(self, *args, **kwargs):
            raise RuntimeError("network unavailable")

        def vision_json(self, *args, **kwargs):
            raise RuntimeError("network unavailable")

    verdict = reviewer.review_frames(
        BrokenProvider(),
        LessonBlueprint(
            topic="T", audience="A", learning_goal="G",
            scenes=[SceneBrief(id="x", title="X", scene_type=SceneType.IMAGE, visual_brief="X")],
        ).style,
        [image],
        scene_title="X",
        visual_brief="X",
    )
    assert not verdict.passed
    assert verdict.review_error


def test_review_error_does_not_burn_repair_budget(tmp_path, ffmpeg) -> None:
    request = HarnessRequest(request_id="test", topic="T", max_review_rounds=2)
    cfg = Config(request=request, run_dir=tmp_path)
    cfg.ensure_dirs()
    blueprint = _image_blueprint()

    class FlakyProvider(FakeProvider):
        def vision_json(self, *args, **kwargs):
            raise RuntimeError("boom")

    provider = FlakyProvider()
    rendered = workflow.run_repair_loop(cfg, provider, blueprint)
    assert rendered[0].review_error
    assert provider.calls.count("image") == 1  # never re-prepared because of a reviewer outage
    assert (tmp_path / "debug" / "image_HITL.txt").is_file()


def test_checkpoint_flow_reaches_strict_bundle(tmp_path, ffmpeg) -> None:
    request = HarnessRequest(request_id="e2e", topic="T")
    cfg = Config(request=request, run_dir=tmp_path)
    cfg.ensure_dirs()
    blueprint = _image_blueprint()
    cfg.blueprint_path.write_text(blueprint.model_dump_json(indent=2), encoding="utf-8")
    provider = FakeProvider()
    prepared = workflow.prepare_all(cfg, provider, blueprint)
    rendered = workflow.render_all(cfg, blueprint, prepared)
    reviewed = workflow.review_all(cfg, provider, blueprint, rendered)
    assert reviewed[0].review_passed
    from eduharness.stage3.bundler import build_bundle

    manifest = build_bundle(tmp_path, blueprint, reviewed, "e2e")
    assert (tmp_path / "bundle" / "index.html").is_file()
    assert (tmp_path / "bundle" / "interactive-runtime.js").is_file()
    assert (tmp_path / "bundle" / "media" / "image.mp3").is_file()
    assert manifest.timeline[0].type == "image"
    assert manifest.timeline[0].audio_src == "media/image.mp3"
    assert manifest.timeline[0].narration == "A short narration."


def test_sanitize_reindents_first_line_and_dedents() -> None:
    body = sanitize_construct_body(
        "t = Text('x')\n"
        "    self.play(Write(t))\n"
        "    self.wait(0.5)\n"
    )
    assert body.splitlines() == ["t = Text('x')", "self.play(Write(t))", "self.wait(0.5)"]
    validate_construct_body(body)


def _fake_manim_run(returncode: int, stderr: str = ""):
    class _P:
        pass

    def run(cfg, scene, blueprint, work, body, class_name):
        p = _P()
        p.returncode = returncode
        p.stdout = ""
        p.stderr = stderr
        run.bodies.append(body)
        return p, "subprocess"

    run.bodies = []
    return run


def test_plain_text_downgrade_never_overwrites_the_latex_spec(tmp_path, monkeypatch) -> None:
    """A no-LaTeX rewrite is a render-time downgrade, not a repair. Writing it back
    into the spec burns the formulas into the run, so a later re-render on a machine
    that *does* have TeX can never recover them -- which is exactly how a shipped
    scene ended up reading `tau_mathrmcw` instead of an equation."""
    bs = chr(92)
    body = "f = MathTex(r'" + bs + "tau_{" + bs + "mathrm{cw}}')\nself.play(Write(f))\nself.wait(0.5)"
    scene = SceneBrief(
        id="s1", title="T", narration="n.", scene_type=SceneType.MANIM,
        visual_brief="v", key_elements=["an equation"],
    )
    blueprint = LessonBlueprint(topic="T", audience="a", learning_goal="g", scenes=[scene])
    cfg = Config(request=HarnessRequest(request_id="t", topic="T"), run_dir=tmp_path)
    cfg.ensure_dirs()
    work = tmp_path / "work" / "s1"
    work.mkdir(parents=True)

    # First attempt fails with a TeX error; the demathified retry succeeds.
    calls = {"n": 0}

    def run(cfg_, scene_, bp_, work_, candidate, class_name):
        calls["n"] += 1
        class _P:
            returncode = 0 if calls["n"] > 1 else 1
            stdout = ""
            stderr = "" if calls["n"] > 1 else "! LaTeX Error: undefined control sequence"
        run.last = candidate
        return _P(), "subprocess"

    monkeypatch.setattr(workflow, "_run_manim", run)
    monkeypatch.setattr(workflow.manim_adapter, "_find_mp4", lambda w, sid: None)
    monkeypatch.setattr(workflow.manim_adapter, "latex_available", lambda: True)

    # _find_mp4 returning None on the success attempt would fall through, so hand
    # back a real file instead.
    produced = work / "s1.mp4"
    produced.write_bytes(b"\x00")
    monkeypatch.setattr(
        workflow.manim_adapter, "_find_mp4",
        lambda w, sid: produced if calls["n"] > 1 else None,
    )

    mode, _guard, final_body, durable = workflow._render_manim_checkpoint(
        cfg, scene, blueprint, work, tmp_path / "out.mp4", body, "EduScene", None
    )
    assert mode.endswith("no-latex")
    assert "mathrm" not in final_body and "τ_cw" in final_body
    assert durable is False, "a plain-text downgrade must not be promoted into the spec"
