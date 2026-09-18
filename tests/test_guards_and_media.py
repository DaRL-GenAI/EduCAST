"""Deterministic guards: Manim layout guard parsing, blank frames, narration mux, image compose."""

from __future__ import annotations

import json

from pathlib import Path

from PIL import Image

from eduharness.schema import (
    GuardFinding,
    GuardReport,
    SceneBrief,
    SceneRepair,
    SceneType,
    StyleConfig,
)
from eduharness.stage2 import media
from eduharness.stage2.adapters import image as image_adapter
from eduharness.stage2.adapters import manim as manim_adapter
from eduharness.stage2.reviewer import _ReviewOut, _to_repair
from tests.conftest import make_video


def test_guard_report_parsing_and_flagged_seconds(tmp_path) -> None:
    (tmp_path / "guard.json").write_text(json.dumps({
        "findings": [
            {"kind": "text_overlap", "severity": "blocker", "message": "a overlaps b", "at_seconds": 3.2,
             "subjects": ["a", "b"]},
            {"kind": "text_out_of_frame", "severity": "major", "message": "c near edge", "at_seconds": 3.3},
            {"kind": "text_out_of_frame", "severity": "major", "message": "d near edge", "at_seconds": 9.0},
        ],
        "checked_steps": 7,
        "source": "manim-layout-guard",
    }), encoding="utf-8")
    report = manim_adapter.parse_guard_report(tmp_path)
    assert report.checked_steps == 7
    assert len(report.blocking()) == 1
    assert report.flagged_seconds() == [3.2, 9.0]
    assert manim_adapter.parse_guard_report(tmp_path / "nope").findings == []


def test_guard_blockers_override_lenient_vlm() -> None:
    scene = SceneBrief(id="s", title="S", scene_type=SceneType.MANIM, visual_brief="b",
                       key_elements=["lever", "formula"])
    guard = GuardReport(findings=[
        GuardFinding(kind="text_overlap", severity="blocker", message="'x' overlaps 'y'", at_seconds=2.0),
        GuardFinding(kind="text_out_of_frame", severity="major", message="'z' violates the safe padding"),
    ])
    out = _ReviewOut(score=9, brief_adherence=9, present_key_elements=["lever", "formula"])
    repair = _to_repair(out, scene, guard, pass_score=7.0)
    assert not repair.passed
    assert any("overlaps" in b for b in repair.blocking_issues)
    assert any("safe padding" in m for m in repair.minor_issues)
    assert repair.needs_repair()

    clean = _to_repair(out, scene, GuardReport(), pass_score=7.0)
    assert clean.passed and clean.fix_action == "noop"


def test_measured_major_text_overlap_is_still_blocking() -> None:
    scene = SceneBrief(id="s", title="S", scene_type=SceneType.MANIM, visual_brief="b")
    guard = GuardReport(findings=[
        GuardFinding(kind="text_overlap", severity="major", message="'label' overlaps 'shape'"),
    ])
    out = _ReviewOut(score=9, brief_adherence=9)
    repair = _to_repair(out, scene, guard, pass_score=7.0)
    assert not repair.passed
    assert repair.blocking_issues and "overlaps" in repair.blocking_issues[0]


def test_review_fails_on_unclassified_key_element() -> None:
    scene = SceneBrief(id="s", title="S", scene_type=SceneType.REMOTION, visual_brief="b",
                       key_elements=["equation", "comparison"])
    out = _ReviewOut(score=9, brief_adherence=9, present_key_elements=["equation"])
    repair = _to_repair(out, scene, GuardReport(), pass_score=7.0)
    assert not repair.passed
    assert "Missing key element: comparison" in repair.blocking_issues


def test_grid_anchor_collisions_are_reported() -> None:
    from eduharness.stage2.reviewer import _grid_layout_findings

    findings = _grid_layout_findings(
        "self.place_at_grid(label_a, 'B2')\nself.place_at_grid(label_b, 'B2')"
    )
    # Its own kind, not `text_overlap`: this is a regex over source, and
    # `text_overlap` is the channel for measured geometry, which _to_repair
    # makes blocking regardless of severity.
    assert findings and findings[0].kind == "grid_anchor_overlap"
    assert findings[0].severity == "major"


def test_grid_anchor_overlap_does_not_fail_a_clean_scene() -> None:
    """Sequential reuse of one region is what the Manim prompt teaches.

    The static scan has no notion of time, so it reads the FadeOut/re-place
    pattern as a collision. It must stay advisory: the VLM looked at the frames
    and saw no defect, so the scene passes with the anchor note as a nit.
    """
    from eduharness.stage2.reviewer import _grid_layout_findings

    scene = SceneBrief(id="s", title="S", scene_type=SceneType.MANIM, visual_brief="b",
                       key_elements=["beam"])
    guard = GuardReport(findings=_grid_layout_findings(
        "self.place_in_area(brace_a, 'E1', 'E6')\n"
        "self.play(FadeOut(brace_a))\n"
        "self.place_in_area(brace_b, 'E1', 'E6')\n"
    ))
    assert guard.findings, "the scan should still report the shared anchors"
    out = _ReviewOut(score=9, brief_adherence=9, present_key_elements=["beam"])
    repair = _to_repair(out, scene, guard, pass_score=7.0)
    assert repair.passed and repair.fix_action == "noop"
    assert any("grid anchors" in issue for issue in repair.minor_issues)


def test_scene_repair_finalize_rules() -> None:
    low = SceneRepair(score=5.5, blocking_issues=[]).finalize(pass_score=7.0)
    assert not low.passed and low.severity == "major"
    minor_only = SceneRepair(score=8.0, minor_issues=["font drift"]).finalize(pass_score=7.0)
    assert minor_only.passed and minor_only.fix_action == "noop" and not minor_only.needs_repair()
    legacy = SceneRepair.model_validate({"passed": False, "score": 3, "issues": ["cut off"]})
    assert legacy.blocking_issues == ["cut off"]
    assert "MUST FIX" in legacy.feedback_text()


def test_blank_frame_detection(tmp_path, ffmpeg) -> None:
    video = make_video(tmp_path / "v.mp4", seconds=2.0, color="black")
    frames = media.extract_video_frames(video, tmp_path / "frames", "v", count=3, extra_seconds=[0.5])
    assert len(frames) == 4
    assert any(f.label == "guard" for f in frames)
    findings = media.blank_frame_findings(frames)
    assert findings and findings[0].severity == "blocker"


def test_mux_narration_pads_shorter_track(tmp_path, ffmpeg) -> None:
    video = make_video(tmp_path / "v.mp4", seconds=1.0, color="blue")
    audio = tmp_path / "n.mp3"
    import subprocess

    subprocess.run([media.ffmpeg_bin(), "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "3", str(audio)],
                   check=True, capture_output=True)
    out = tmp_path / "out.mp4"
    duration = media.mux_narration(video, audio, out)
    assert out.is_file()
    assert 3.3 <= duration <= 4.2  # audio length + tail
    probe = subprocess.check_output(
        [media.ffprobe_bin(), "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(out)],
        text=True,
    )
    assert "video" in probe and "audio" in probe


def test_image_compose_draws_caption_inside_board(tmp_path) -> None:
    src = tmp_path / "src.png"
    Image.new("RGB", (1536, 1024), "#336699").save(src)
    style = StyleConfig()
    out = image_adapter.compose_final(src, tmp_path / "out.png", style, title="Lever intuition",
                                      caption="Heavier closer can balance lighter farther")
    with Image.open(out) as img:
        assert img.size == (1920, 1080)
        # the caption band paints the style background over the source image, so the
        # pixel must land far closer to the board colour than to the illustration
        px = img.getpixel((200, 1040))
        ground = tuple(int(style.palette.background.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        source = (0x33, 0x66, 0x99)
        near = sum((a - b) ** 2 for a, b in zip(px, ground))
        far = sum((a - b) ** 2 for a, b in zip(px, source))
        assert near < far / 4, (px, ground, source)


def test_image_brief_keeps_key_elements_and_label_language() -> None:
    brief = SceneBrief(id="i", title="I", scene_type=SceneType.IMAGE, visual_brief="a see-saw",
                       key_elements=["see-saw", "two children"])
    prompt = image_adapter.build_prompt(brief, StyleConfig(), audience="Grade 9", language="Chinese")
    assert "Teaching language for the image labels: Chinese" in prompt
    assert "Grade 9" in prompt
    assert "see-saw; two children" in prompt


def test_concept_image_preserves_edges_and_colors(tmp_path) -> None:
    # Labels at any edge must survive fitting; local chrome must not cover them.
    src = tmp_path / "diagram.png"
    art = Image.new("RGB", (300, 200), "#336699")
    for x, y, color in [(0, 0, "red"), (299, 0, "green"),
                        (0, 199, "blue"), (299, 199, "yellow")]:
        from PIL import ImageDraw
        ImageDraw.Draw(art).rectangle((max(0, x-15), max(0, y-15),
                                       min(299, x+15), min(199, y+15)), fill=color)
    art.save(src)
    out = image_adapter.compose_concept_image(src, tmp_path / "out.png", StyleConfig())
    with Image.open(out) as result:
        assert result.size == (1920, 1080)
        # 3:2 art occupies x=150..1769, the full height; all four corners survive.
        assert result.getpixel((160, 10)) == (255, 0, 0)
        assert result.getpixel((1759, 10)) == (0, 128, 0)
        assert result.getpixel((160, 1069)) == (0, 0, 255)
        assert result.getpixel((1759, 1069)) == (255, 255, 0)
        assert result.getpixel((960, 540)) == (51, 102, 153)


def test_unreadable_guard_report_fails_closed(tmp_path) -> None:
    """An unparseable report used to come back as an empty GuardReport, which every
    caller reads as "the guard found nothing" -- a silent pass from the one component
    whose job is to fail loudly. It must surface as a blocker instead."""
    from eduharness.stage2.adapters.manim import parse_guard_report

    (tmp_path / "guard.json").write_text(
        json.dumps({"findings": [{"kind": "not_a_real_kind", "message": "x"}],
                    "checked_steps": 4}),
        encoding="utf-8",
    )
    report = parse_guard_report(tmp_path)
    assert report.blocking(), "a report that cannot be parsed must not read as clean"
    assert report.blocking()[0].kind == "guard_unreadable"

    missing = parse_guard_report(tmp_path / "nope")
    assert missing.source.endswith("missing")


def test_concept_image_on_board_keeps_art_colours_and_chrome(tmp_path) -> None:
    """With a brief the diagram lands in regions.main: board chrome around it, art
    colours untouched (no palette snap) and its own ground faded into the board."""
    from eduharness.schema import teaching_board

    style = StyleConfig()
    art = Image.new("RGB", (1536, 1024), "#FEFAEE")  # the near-white ground a model picks
    from PIL import ImageDraw
    ImageDraw.Draw(art).ellipse((600, 400, 900, 620), fill="#E0A82E")  # a gold mark to track
    src = tmp_path / "diagram.png"
    art.save(src)
    brief = SceneBrief(id="s2", title="Longer Arm, Bigger Twist", scene_type=SceneType.IMAGE,
                       visual_brief="a see-saw", lecture_lines=["A lever turns around a fulcrum"],
                       takeaway="Longer arm, bigger turn")
    out = image_adapter.compose_concept_image(src, tmp_path / "out.png", style, brief=brief)

    board = teaching_board(style, brief)
    x, y, w, h = (round(board["regions"]["main"][k]) for k in ("x", "y", "width", "height"))
    ground = tuple(int(style.palette.background.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    with Image.open(out) as result:
        assert result.size == (style.layout.width, style.layout.height)
        # The gold mark keeps its exact hex: snapping would pull it onto a palette colour.
        assert result.getpixel((x + w // 2, y + h // 2)) == (0xE0, 0xA8, 0x2E)
        # The art's own ground is gone, so no panel edge shows inside the region.
        assert result.getpixel((x + 8, y + 8)) == ground
        # Board chrome still owns the title band above the region.
        assert y > style.layout.height * style.layout.title_ratio


def test_title_card_is_its_own_stage_with_the_cast(tmp_path) -> None:
    """Contract 1: the opener is not a board — no lecture column, no result strip —
    and the cast leans in from both bottom corners. The Pillow fallback must draw
    the same still the Remotion template does, so a missing Chrome is invisible."""
    from eduharness.stage2.adapters import remotion as remotion_adapter
    from eduharness.stage2.media import ffmpeg_available

    if not ffmpeg_available():
        import pytest

        pytest.skip("ffmpeg is unavailable")

    style = StyleConfig()
    brief = SceneBrief(id="s1-intro", title="Torque & Lever Balance", scene_type=SceneType.REMOTION,
                       visual_brief="opener", lecture_lines=["Torque turns things"],
                       takeaway="Force times distance")
    spec = remotion_adapter.RemotionSpec(beat="title_card", title="Torque & Lever Balance",
                                         subtitle="Force x distance around a fulcrum")
    remotion_adapter.render_fallback_slide(brief, style, spec, tmp_path, tmp_path / "title.mp4", 3.0)

    ground = tuple(int(style.palette.background.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    with Image.open(tmp_path / "s1-intro_title.png") as still:
        w, h = still.size
        assert (w, h) == (style.layout.width, style.layout.height)

        def painted(box) -> int:
            return sum(1 for px in still.crop(box).getdata() if px != ground)

        # Cast in both bottom corners...
        assert painted((0, round(h * 0.75), round(w * 0.25), h)) > 5000
        assert painted((round(w * 0.75), round(h * 0.75), w, h)) > 5000
        # ...and nothing where the board would put its lecture column (the cast
        # itself starts below 0.6h, so this strip is board chrome or nothing).
        assert painted((0, round(h * 0.2), round(w * 0.2), round(h * 0.6))) == 0


def test_opener_is_pinned_to_the_title_card() -> None:
    """Contract 1 is enforced in code, not in the prompt: the model picked `formula`
    for an opener once, which put a lecture column and a result strip on the title
    screen. Whatever beat comes back, the opener ends up a title card."""
    from eduharness.stage2.adapters import remotion as remotion_adapter

    board_beat = remotion_adapter.RemotionSpec(
        beat="formula", title="Ohm's Law", subtitle="How voltage and resistance set current.",
        bullets=["Ohm's law links I, V and R."], formula="I = V / R", highlights=["I", "V", "R"],
        steps=["title:fade-in"], right_items=["Label near I"],
    )
    pinned = remotion_adapter.as_title_card(board_beat)
    assert pinned.beat == "title_card"
    assert pinned.title == "Ohm's Law" and pinned.subtitle.startswith("How voltage")
    for field in remotion_adapter.TITLE_CARD_ONLY_FIELDS:
        assert not getattr(pinned, field), field


def test_result_strip_text_keeps_clear_of_the_character(tmp_path) -> None:
    """The character is pasted over the result strip, so the takeaway has to be laid
    out in the room left of it — it used to run underneath and lose its last words."""
    style = StyleConfig()
    brief = SceneBrief(id="s2", title="A Flow Analogy", scene_type=SceneType.IMAGE,
                       visual_brief="a pipe", lecture_lines=["Voltage pushes"],
                       takeaway="Voltage pushes, resistance opposes, current is the resulting flow.")
    board = image_adapter.draw_teaching_board(style, brief)
    placed = image_adapter._character_art(style, board.size, brief.id)
    assert placed is not None, "this test needs the character art"
    _, char_left, char_top = placed

    # The board minus its takeaway: whatever differs is the takeaway's own ink, and
    # none of it may fall in the column the character is about to cover.
    bare = image_adapter.draw_teaching_board(style, brief.model_copy(update={"takeaway": ""}))
    from PIL import ImageChops

    ink = ImageChops.difference(board, bare)
    assert ink.getbbox(), "the takeaway drew nothing at all"
    assert ink.crop((char_left, char_top, board.size[0], board.size[1])).getbbox() is None, \
        "takeaway text runs under the character"


def test_rejected_guard_retry_restores_the_first_render(tmp_path, monkeypatch) -> None:
    """A rejected re-render must not leave its video behind.

    The retry writes to the same media/<id>.mp4 as the first attempt, so when its
    guard score is no better the file has to go back — otherwise the returned
    RenderedScene (first render's guard + visual_seconds) describes a video that
    is no longer on disk, and the restored spec marks the scene current forever.
    """
    from eduharness.config import Config
    from eduharness.schema import HarnessRequest, LessonBlueprint, PreparedScene, RenderedScene
    from eduharness.stage2 import workflow
    from eduharness.stage2.adapters import manim as manim_adapter

    scene = SceneBrief(id="s1", title="S", scene_type=SceneType.MANIM, visual_brief="b")
    blueprint = LessonBlueprint(topic="t", audience="a", learning_goal="g",
                                style=StyleConfig(), scenes=[scene])
    cfg = Config(request=HarnessRequest(topic="t"), run_dir=tmp_path)
    (tmp_path / "media").mkdir()
    (tmp_path / "work" / scene.id).mkdir(parents=True)
    (tmp_path / "media" / "s1.mp4").write_bytes(b"FIRST-RENDER")
    (tmp_path / "work" / "s1" / "s1_silent.mp4").write_bytes(b"FIRST-SILENT")
    spec = tmp_path / "work" / "s1" / "spec.json"
    spec.write_text(json.dumps({"construct_body": "original", "scene_class_name": "EduScene"}),
                    encoding="utf-8")

    prepared = PreparedScene(scene_id=scene.id, scene_type=SceneType.MANIM,
                             spec_path="work/s1/spec.json")
    first = RenderedScene(
        scene_id=scene.id, scene_type=SceneType.MANIM, src="media/s1.mp4",
        visual_seconds=12.0,
        guard=GuardReport(findings=[GuardFinding(
            kind="text_overlap", severity="blocker", message="'a' overlaps 'b'")]),
    )

    class _Body:
        construct_body = "rewritten"
        scene_class_name = "EduScene"

    monkeypatch.setattr(manim_adapter, "generate_construct",
                        lambda *a, **k: _Body())

    def fake_render(cfg_, blueprint_, scene_, prepared_, provider_):
        # The real renderer overwrites the same paths; reproduce exactly that.
        (tmp_path / "media" / "s1.mp4").write_bytes(b"RETRY-RENDER")
        (tmp_path / "work" / "s1" / "s1_silent.mp4").write_bytes(b"RETRY-SILENT")
        return RenderedScene(
            scene_id=scene_.id, scene_type=SceneType.MANIM, src="media/s1.mp4",
            visual_seconds=7.0,
            guard=GuardReport(findings=[  # no better than the first render
                GuardFinding(kind="text_overlap", severity="blocker", message="'a' overlaps 'b'"),
                GuardFinding(kind="text_overlap", severity="blocker", message="'c' overlaps 'd'"),
            ]),
        )

    monkeypatch.setattr(workflow, "_render_one", fake_render)
    kept = workflow._retry_on_guard_blockers(
        cfg, blueprint, scene, prepared, first, provider=object()
    )

    assert kept is first, "the worse retry must not be adopted"
    assert (tmp_path / "media" / "s1.mp4").read_bytes() == b"FIRST-RENDER"
    assert (tmp_path / "work" / "s1" / "s1_silent.mp4").read_bytes() == b"FIRST-SILENT"
    assert json.loads(spec.read_text(encoding="utf-8"))["construct_body"] == "original"
    assert not list((tmp_path / "media").glob("*pre_guard_retry*")), "no scratch files left"


def test_improved_guard_retry_keeps_the_new_render(tmp_path, monkeypatch) -> None:
    from eduharness.config import Config
    from eduharness.schema import HarnessRequest, LessonBlueprint, PreparedScene, RenderedScene
    from eduharness.stage2 import workflow
    from eduharness.stage2.adapters import manim as manim_adapter

    scene = SceneBrief(id="s1", title="S", scene_type=SceneType.MANIM, visual_brief="b")
    blueprint = LessonBlueprint(topic="t", audience="a", learning_goal="g",
                                style=StyleConfig(), scenes=[scene])
    cfg = Config(request=HarnessRequest(topic="t"), run_dir=tmp_path)
    (tmp_path / "media").mkdir()
    (tmp_path / "work" / scene.id).mkdir(parents=True)
    (tmp_path / "media" / "s1.mp4").write_bytes(b"FIRST-RENDER")
    spec = tmp_path / "work" / "s1" / "spec.json"
    spec.write_text(json.dumps({"construct_body": "original", "scene_class_name": "EduScene"}),
                    encoding="utf-8")
    prepared = PreparedScene(scene_id=scene.id, scene_type=SceneType.MANIM,
                             spec_path="work/s1/spec.json")
    first = RenderedScene(
        scene_id=scene.id, scene_type=SceneType.MANIM, src="media/s1.mp4",
        guard=GuardReport(findings=[GuardFinding(
            kind="text_overlap", severity="blocker", message="'a' overlaps 'b'")]),
    )

    class _Body:
        construct_body = "rewritten"
        scene_class_name = "EduScene"

    monkeypatch.setattr(manim_adapter, "generate_construct", lambda *a, **k: _Body())

    def fake_render(cfg_, blueprint_, scene_, prepared_, provider_):
        (tmp_path / "media" / "s1.mp4").write_bytes(b"RETRY-RENDER")
        return RenderedScene(scene_id=scene_.id, scene_type=SceneType.MANIM,
                             src="media/s1.mp4", guard=GuardReport())

    monkeypatch.setattr(workflow, "_render_one", fake_render)
    out = workflow._retry_on_guard_blockers(
        cfg, blueprint, scene, prepared, first, provider=object()
    )

    assert out is not first
    assert (tmp_path / "media" / "s1.mp4").read_bytes() == b"RETRY-RENDER"
    assert json.loads(spec.read_text(encoding="utf-8"))["construct_body"] == "rewritten"
    assert not list((tmp_path / "media").glob("*pre_guard_retry*")), "no scratch files left"


def test_static_grid_hint_is_not_presented_as_measured(monkeypatch) -> None:
    """The prompt must not hand a source heuristic to the reviewer as a measurement.

    The reviewer trusts the "measured, not guessed" header and repeats whatever it
    contains as a defect of its own — which put the grid-anchor guess straight back
    into blocking_issues through the VLM after `_to_repair` stopped promoting it.
    """
    from eduharness.stage2 import reviewer as rv

    scene = SceneBrief(id="s", title="S", scene_type=SceneType.MANIM, visual_brief="b")
    guard = GuardReport(findings=[
        GuardFinding(kind="grid_anchor_overlap", severity="major",
                     message="Code2Video grid anchors for a and b share E1"),
        GuardFinding(kind="text_overlap", severity="blocker",
                     message="'x' overlaps 'y'", at_seconds=2.0),
    ])
    seen: dict[str, str] = {}

    class P:
        def vision_json(self, prompt, images, schema, **kw):
            seen["prompt"] = prompt
            return _ReviewOut(score=9, brief_adherence=9)

    monkeypatch.setattr(rv, "screenshot_html", lambda *a, **k: (None, []))
    rv.review_scene(P(), StyleConfig(), [rv.Frame(path=Path("f.png"), seconds=0.0, label="uniform")],
                    scene=scene, guard=guard, pass_score=7.0)

    prompt = seen["prompt"]
    measured = prompt.split("DETERMINISTIC LAYOUT GUARD FINDINGS")[1].split("STATIC SOURCE HINTS")[0]
    assert "'x' overlaps 'y'" in measured, "a real measurement stays in the measured block"
    assert "grid anchors" not in measured, "the source heuristic must not ride the measured block"
    hints = prompt.split("STATIC SOURCE HINTS")[1]
    assert "grid anchors" in hints
    assert "never make one a blocking issue on its own" in hints
