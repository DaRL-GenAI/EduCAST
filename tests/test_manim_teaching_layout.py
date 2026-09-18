"""Runtime checks for bounded teaching layouts and moving text collisions."""

from __future__ import annotations

import json

import pytest

from eduharness.schema import StyleConfig
from eduharness.stage2.adapters.manim import assemble_script


def _scene_namespace(body: str) -> dict:
    pytest.importorskip("manim")
    namespace: dict = {}
    exec(assemble_script(body, StyleConfig(), "LayoutTestScene"), namespace)
    return namespace


def test_teaching_grid_fits_complete_groups_without_colliding_with_notes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    namespace = _scene_namespace("self.wait(0.1)")
    scene = namespace["LayoutTestScene"]()
    scene.setup_layout(
        "Force and distance determine torque",
        ["Apply a force", "Measure perpendicular distance", "Compare the turning effect"],
        kicker="PHYSICS",
    )
    large = namespace["VGroup"](
        namespace["Rectangle"](width=40, height=15),
        namespace["Text"]("Diagram label", font_size=32).shift(namespace["UP"] * 10),
    )
    scene.place_in_area(large, "A1", "D6")
    left, right, bottom, top = scene._grid_bounds
    assert large.get_left()[0] >= left
    assert large.get_right()[0] <= right
    assert large.get_top()[1] <= top
    assert large.get_bottom()[1] >= bottom + 2 * scene._grid_cell_h
    assert scene.lecture.get_right()[0] < large.get_left()[0]
    scene._guard_check("test")
    report = json.loads((tmp_path / "guard.json").read_text())
    assert report["findings"] == []


def test_guard_detects_transient_text_collision_between_clean_final_poses(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    namespace = _scene_namespace("""
left = label("moving").shift(LEFT * 3)
middle = label("stationary")
self.add(left, middle)
self.play(left.animate.shift(RIGHT * 6), run_time=1.5, rate_func=linear)
self.wait(0.1)
""")
    with namespace["tempconfig"]({
        "dry_run": True,
        "disable_caching": True,
        "pixel_width": 480,
        "pixel_height": 270,
        "frame_rate": 15,
    }):
        namespace["LayoutTestScene"]().render()
    report = json.loads((tmp_path / "guard.json").read_text())
    assert any(item["kind"] == "text_overlap" for item in report["findings"])
    assert report["checked_steps"] > 6


def test_placement_keeps_clear_of_the_reserved_character_corner(tmp_path, monkeypatch):
    """The character owns the bottom-right third; content placed there used to end up
    behind it. A placement over that corner is trimmed to the room beside it, and the
    trimming logic itself keeps the larger of the two remaining boxes."""
    monkeypatch.chdir(tmp_path)
    namespace = _scene_namespace("""
self.setup_layout("Reserved corner", ["one", "two"])
corner = label("bottom right")
self.place_in_area(corner, 'E4', 'F6')
self.add(corner)
self.wait(0.1)
""")
    with namespace["tempconfig"]({
        "dry_run": True, "disable_caching": True,
        "pixel_width": 480, "pixel_height": 270, "frame_rate": 15,
    }):
        namespace["LayoutTestScene"]().render()
    report = json.loads((tmp_path / "guard.json").read_text())
    covered = [item for item in report["findings"]
               if item["kind"] == "text_occluded" and "ImageMobject" in item["subjects"]]
    assert not covered, covered

    scene = namespace["LayoutTestScene"]()
    scene._grid_cell_w, scene._grid_cell_h = 1.0, 1.0
    scene._reserved = (2.0, 6.0, -3.0, 1.0)
    # Untouched when the box is nowhere near the corner.
    assert scene._avoid_reserved(-6.0, -1.0, -1.0, 2.0) == (-6.0, -1.0, -1.0, 2.0)
    # Trimmed to the wider remainder when it overlaps: here the room to the left.
    assert scene._avoid_reserved(-5.0, 5.0, -2.0, 0.5) == (-5.0, 2.0, -2.0, 0.5)
    # And to the room above when that is the bigger piece.
    assert scene._avoid_reserved(1.0, 6.0, -2.5, 4.0) == (1.0, 6.0, 1.0, 4.0)


def test_lecture_column_holds_a_key_scene_five_lines(tmp_path, monkeypatch):
    """A key scene plans five lecture lines; the column used to keep four, so the
    fifth show_step raised and the whole scene fell back to a static slide."""
    monkeypatch.chdir(tmp_path)
    namespace = _scene_namespace("""
self.setup_layout("Five lines", ["one", "two", "three", "four", "five"])
self.show_step(4)
self.wait(0.1)
""")
    with namespace["tempconfig"]({
        "dry_run": True, "disable_caching": True,
        "pixel_width": 480, "pixel_height": 270, "frame_rate": 15,
    }):
        namespace["LayoutTestScene"]().render()
    assert (tmp_path / "guard.json").is_file()


def test_guard_reports_text_crossing_a_curve_without_using_curve_bbox(tmp_path, monkeypatch):
    """A thin graph stroke crossing a label is a blocker; an empty part of its
    bounding box is not treated as covered."""
    monkeypatch.chdir(tmp_path)
    namespace = _scene_namespace("""
self.setup_layout("Curve labels", ["Keep labels beside the curve"])
axes = Axes(x_range=[-3, 3, 1], y_range=[-2, 4, 1], x_length=5, y_length=4)
curve = axes.plot(lambda x: x * x, x_range=[-2, 2], color=PRIMARY_COLOR)
crossing = label("crossing").move_to(axes.c2p(0, 0))
clear = label("clear").move_to(axes.c2p(0.9, 2.8))
self.add(axes, curve, crossing, clear)
self.wait(0.1)
""")
    with namespace["tempconfig"]({
        "dry_run": True, "disable_caching": True,
        "pixel_width": 480, "pixel_height": 270, "frame_rate": 15,
    }):
        namespace["LayoutTestScene"]().render()
    report = json.loads((tmp_path / "guard.json").read_text())
    findings = report["findings"]
    assert any(item["kind"] == "text_occluded" and "crossing" in item["subjects"]
               for item in findings)
    assert any("crossing" in item["subjects"] and "NumberLine" in item["subjects"]
               for item in findings), "axes with tick/tip children must keep their shafts in QA"
    assert not any(item["kind"] == "text_occluded" and "clear" in item["subjects"]
                   for item in findings)


def test_self_annotate_keeps_label_and_leader_together(tmp_path, monkeypatch):
    """The supported annotation helper chooses nearby free space and follows a
    target when that target moves."""
    monkeypatch.chdir(tmp_path)
    namespace = _scene_namespace("""
self.setup_layout("Attached label", ["Keep the annotation near the dot"])
dot = Dot(RIGHT * 1.5, color=PRIMARY_COLOR)
self.add(dot)
annotation = self.annotate(dot, "value", RIGHT, obstacles=(dot,))
self.add(annotation)
self.wait(0.1)
self.play(dot.animate.shift(UP * 0.8), run_time=0.4)
self.wait(0.1)
""")
    with namespace["tempconfig"]({
        "dry_run": True, "disable_caching": True,
        "pixel_width": 480, "pixel_height": 270, "frame_rate": 15,
    }):
        scene = namespace["LayoutTestScene"]()
        scene.render()
    report = json.loads((tmp_path / "guard.json").read_text())
    assert report["findings"] == []
    annotation = next(m for m in scene.mobjects if isinstance(m, namespace["_FollowingAnnotation"]))
    target = annotation._edu_target_ref()
    leader, tag, anchor = annotation.submobjects
    assert target is not None
    assert target.get_center()[1] == pytest.approx(0.8)
    assert tag.get_center()[1] == pytest.approx(target.get_center()[1])
    assert leader.get_start()[1] == pytest.approx(target.get_center()[1])
    assert leader.get_end()[0] == pytest.approx(tag.get_left()[0])


@pytest.mark.parametrize("shape", [
    "Line(LEFT * 2, RIGHT * 2)",
    "Line(DOWN * 2, UP * 2)",
    "Arrow(LEFT * 2, RIGHT * 2)",
    "Rectangle(width=4, height=3, fill_opacity=1, stroke_width=0)",
])
def test_guard_checks_thin_strokes_and_containing_fills(tmp_path, monkeypatch, shape):
    monkeypatch.chdir(tmp_path)
    namespace = _scene_namespace("self.wait(0.1)")
    scene = namespace["LayoutTestScene"]()
    text = namespace["label"]("c = 3")
    geometry = eval(shape, namespace)
    scene.add(geometry, text)
    before = text.get_center().copy()
    scene._guard_check("test")
    report = json.loads((tmp_path / "guard.json").read_text())
    assert any(item["kind"] == "text_occluded" for item in report["findings"])
    assert (text.get_center() == before).all(), "auditing must not detach text from its target"


def test_curve_box_and_disconnected_paths_do_not_cover_empty_space(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    namespace = _scene_namespace("self.wait(0.1)")
    scene = namespace["LayoutTestScene"]()
    # The circle surrounds the text but its actual stroke is nowhere near it.
    ring = namespace["Circle"](radius=2)
    paths = namespace["VMobject"]()
    paths.start_new_path(namespace["LEFT"] * 2)
    paths.add_line_to(namespace["LEFT"])
    paths.start_new_path(namespace["RIGHT"])
    paths.add_line_to(namespace["RIGHT"] * 2)
    scene.add(ring, paths, namespace["label"]("clear"))
    scene._guard_check("test")
    report = json.loads((tmp_path / "guard.json").read_text())
    assert report["findings"] == []


def test_annotations_reserve_nearby_space_and_release_removed_labels(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    namespace = _scene_namespace("self.wait(0.1)")
    scene = namespace["LayoutTestScene"]()
    dot = namespace["Dot"]()
    scene.add(dot)
    first = scene.annotate(dot, "value", namespace["RIGHT"])
    second = scene.annotate(dot, "value", namespace["RIGHT"])
    assert second[1].get_center()[0] < dot.get_center()[0]
    scene.add(first, second)
    scene.remove(first, second)
    replacement = scene.annotate(dot, "value", namespace["RIGHT"])
    assert replacement[1].get_center()[0] > dot.get_center()[0]
    # A label with nowhere clear to go is REPORTED, not fatal. Raising here used
    # to abort the render, so the scene became a placeholder slide and every other
    # animation step was lost -- a far worse outcome than one crowded label.
    scene._guard_findings.clear()
    scene._guard_seen.clear()
    crowded = scene.annotate(dot, "value", obstacles=(namespace["Rectangle"](
        width=8, height=6, fill_opacity=1, stroke_width=0),))
    assert crowded is not None, "a crowded annotation must still be placed"
    assert any(f["kind"] == "annotation_crowded" and f["severity"] == "major"
               for f in scene._guard_findings), "the crowding must be reported to the reviewer"


def test_annotation_keeps_gap_when_target_resizes_or_whole_group_moves(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    namespace = _scene_namespace("self.wait(0.1)")
    scene = namespace["LayoutTestScene"]()
    circle = namespace["Circle"](radius=0.3)
    annotation = scene.annotate(circle, "radius", buff=0.18)
    circle.scale(3)
    annotation.update(0)
    assert annotation[1].get_left()[0] - circle.get_right()[0] == pytest.approx(0.18)
    group = namespace["VGroup"](circle, annotation)
    group.scale(0.5).shift(namespace["UP"])
    before = annotation[1].get_center().copy()
    annotation.update(0)
    assert annotation[1].get_center() == pytest.approx(before)
    assert annotation[1].get_left()[0] - circle.get_right()[0] == pytest.approx(0.09)
    copied = annotation.copy()
    scene.add(circle, copied)
    scene._guard_check("test")
    assert scene._guard_findings == [], "an annotation copy must not collide with its own leader"


def test_whole_diagram_transform_keeps_annotations_attached_in_every_pose(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    namespace = _scene_namespace("self.wait(0.1)")
    scene = namespace["LayoutTestScene"]()
    dot = namespace["Dot"]()
    annotation = scene.annotate(dot, "value")
    group = namespace["VGroup"](dot, annotation)
    copied = group.copy().shift(namespace["RIGHT"] * 2)
    assert copied[1]._edu_target_ref() is copied[0]
    animation = namespace["Transform"](group, copied)
    animation.begin()
    offset = annotation[1].get_center() - dot.get_center()
    for alpha in (0.25, 0.5, 0.75, 1):
        animation.update_mobjects(0.1)
        animation.interpolate(alpha)
        assert annotation[1].get_center() - dot.get_center() == pytest.approx(offset)
    animation.finish()
    legacy = namespace["annotate"](dot, "legacy").copy()
    scene.add(dot, legacy)
    scene._guard_check("test")
    assert scene._guard_findings == []


def test_annotation_stays_in_target_area_above_result_strip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    namespace = _scene_namespace("self.wait(0.1)")
    scene = namespace["LayoutTestScene"]()
    scene.setup_layout("Region boundaries", ["Keep the result strip clear"])
    dot = namespace["Dot"]()
    scene.place_in_area(dot, "A1", "D6")
    left, right, bottom, top = dot._edu_annotation_bounds
    dot.move_to([(left + right) / 2, bottom + 0.1, 0])
    scene.add(dot)
    annotation = scene.annotate(dot, "value", namespace["DOWN"])
    assert annotation[1].get_bottom()[1] >= bottom
    assert annotation[1].get_top()[1] <= top


def test_stroke_clearance_does_not_change_with_output_resolution(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    namespace = _scene_namespace("self.wait(0.1)")
    scene = namespace["LayoutTestScene"]()
    line = namespace["Line"](namespace["LEFT"], namespace["RIGHT"], stroke_width=4)
    checks = []
    for width in (480, 1920):
        with namespace["tempconfig"]({"pixel_width": width}):
            checks.append(scene._shape_crosses_box(line, -0.1, 0.1, 0.065, 0.2))
    assert checks == [False, False]


def test_repeated_reveal_keeps_visible_geometry_in_every_frame(tmp_path, monkeypatch):
    """show_step already reveals its objects; repeating reveal must not blink."""
    monkeypatch.chdir(tmp_path)
    ns = _scene_namespace('self.wait(0.1)')
    samples = []

    class RepeatedReveal(ns['LayoutTestScene']):
        def construct(self):
            self.setup_layout('Continuity', ['An arrow remains visible'])
            self.arrow = ns['Arrow'](ns['LEFT'], ns['RIGHT'])
            self.place_in_area(self.arrow, 'A1', 'D6')
            self.show_step(0, self.arrow)
            self.monitor = True
            self.always_update_mobjects = True
            self.reveal(self.arrow)
            self.wait(0.2)

        def update_to_time(self, t):
            super().update_to_time(t)
            if getattr(self, 'monitor', False):
                visible = self.arrow in self.get_mobject_family_members()
                samples.append((visible, self.arrow.get_stroke_opacity()))

    with ns['tempconfig']({'dry_run': True, 'disable_caching': True,
                           'pixel_width': 480, 'pixel_height': 270, 'frame_rate': 15}):
        RepeatedReveal().render()
    assert samples, 'check every frame of the repeated entrance'
    assert all(visible and opacity > 0.95 for visible, opacity in samples)
    assert (tmp_path / "guard.json").is_file()
    report = json.loads((tmp_path / "guard.json").read_text())
    assert report["findings"] == []


def test_reveal_new_child_does_not_restart_existing_sibling_and_allows_reentry(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ns = _scene_namespace('self.wait(0.1)')
    samples = []

    class MixedReveal(ns['LayoutTestScene']):
        def construct(self):
            self.existing = ns['Dot'](ns['LEFT'])
            fresh = ns['Dot'](ns['RIGHT'])
            group = ns['VGroup'](self.existing, fresh)
            self.add(self.existing)
            self.monitor = True
            # Duplicate and nested arguments must still produce only one entry.
            self.reveal(self.existing, group, group, fresh, run_time=0.4)
            self.monitor = False
            self.play(ns['FadeOut'](fresh), run_time=0.2)
            assert fresh not in self.get_mobject_family_members()
            self.reveal(fresh, run_time=0.4)
            assert fresh in self.get_mobject_family_members()
            assert fresh.get_fill_opacity() == pytest.approx(1.0)

        def update_to_time(self, t):
            super().update_to_time(t)
            if getattr(self, 'monitor', False):
                samples.append(self.existing.get_fill_opacity())

    with ns['tempconfig']({'dry_run': True, 'disable_caching': True,
                           'pixel_width': 480, 'pixel_height': 270, 'frame_rate': 15}):
        MixedReveal().render()
    assert samples and min(samples) > 0.95
