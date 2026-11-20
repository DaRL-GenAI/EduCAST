"""Visual defects must reach repair even when a lenient reviewer misclassifies them."""

import pytest

from eduharness.schema import GuardReport, RepairOp, SceneBrief, SceneType
from eduharness.stage2.reviewer import _ReviewOut, _to_repair


@pytest.mark.parametrize("field, issue", [
    ("layout_issues", "At 6.2s, 'c = 3' overlaps the 'y-intercept' label; move it beside the graph."),
    ("layout_issues", "At 6.2s, the label 'c = 3' crosses the green curve."),
    ("layout_issues", "At 6.2s, the annotation 'c = 3' intersects the y-axis."),
    ("minor_issues", "At 6.2s, the label 'c = 3' covers the arrow tip."),
    ("minor_issues", "At 6.2s, the labels 'c = 3' and 'c = -2' collide."),
    ("layout_issues", "At 6.2s, the label 'c = 3' is covered by the upward arrow."),
    ("minor_issues", "At 6.2s, the label 'c = 3' is unreadable under the curve."),
    ("temporal_issues", "At 8.0s, the old 'c = 3' label remains beside the new graph after the state changes."),
    ("temporal_issues", "The final frame contains a stale 'y-intercept' label from the previous state."),
])
def test_observed_annotation_defect_blocks_lenient_review(field, issue):
    scene = SceneBrief(id="s", title="S", scene_type=SceneType.MANIM, visual_brief="Quadratic graph")
    out = _ReviewOut(score=9, brief_adherence=9, fix_action="noop", **{field: [issue]})

    repair = _to_repair(out, scene, GuardReport(), pass_score=7)

    assert not repair.passed
    assert repair.needs_repair()
    assert repair.fix_action == "re_render"
    assert repair.blocking_issues == [issue]
    assert issue not in repair.minor_issues


@pytest.mark.parametrize("issue", [
    "The label is slightly left of the preferred position, with a clear association to the curve.",
    "Move the label into a non-overlapping region to improve alignment.",
    "The label could move right to avoid overlap on a future state.",
    "No labels overlap; slightly increase the spacing for polish.",
    "The labels are not overlapping, though the font differs from the style board.",
    "The parabola crosses the x-axis while the labels remain readable.",
    "The previous state label remains visible for deliberate side-by-side comparison.",
])
def test_layout_preference_and_intentional_geometry_remain_minor(issue):
    scene = SceneBrief(id="s", title="S", scene_type=SceneType.MANIM, visual_brief="Quadratic graph")
    out = _ReviewOut(score=9, brief_adherence=9, layout_issues=[issue])

    repair = _to_repair(out, scene, GuardReport(), pass_score=7)

    assert repair.passed
    assert not repair.needs_repair()
    assert repair.blocking_issues == []
    assert repair.minor_issues == [issue]


def test_annotation_collision_keeps_targeted_body_repair():
    scene = SceneBrief(id="s", title="S", scene_type=SceneType.MANIM, visual_brief="Quadratic graph")
    issue = "At 6.2s, the label 'c = 3' overlaps the curve."
    op = RepairOp(target="construct_body", op="replace",
                  before="annotate(curve, 'c = 3', direction=DOWN)",
                  after="annotate(curve, 'c = 3', direction=RIGHT)")
    out = _ReviewOut(score=9, brief_adherence=9, fix_action="noop",
                     minor_issues=[issue], layout_issues=[issue], ops=[op])

    repair = _to_repair(out, scene, GuardReport(), pass_score=7)

    assert not repair.passed
    assert repair.fix_action == "patch_artifact"
    assert repair.ops == [op]
    assert repair.blocking_issues == [issue]
    assert repair.minor_issues == []
