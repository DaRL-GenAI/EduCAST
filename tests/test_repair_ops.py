"""Unit tests for diff-style SceneRepair applicators."""

from __future__ import annotations

from eduharness.schema import RepairOp, SceneRepair
from eduharness.stage2.repair_apply.image_ops import (
    apply_image_ops,
    prompt_addendum_from_ops,
)
from eduharness.stage2.repair_apply.interactive_ops import apply_interactive_ops
from eduharness.stage2.repair_apply.manim_ops import apply_manim_ops
from eduharness.stage2.repair_apply.remotion_ops import apply_remotion_ops
from eduharness.stage2.adapters import image as image_adapter
from eduharness.stage2.adapters.remotion import RemotionSpec
from eduharness.schema import SceneBrief, SceneType, StyleConfig


def test_manim_unique_replace():
    body = "title = Text('Hello')\nlabel = Text('World')\n"
    ops = [RepairOp(target="construct_body", op="replace", before="Text('Hello')", after="Text('Torque')")]
    result = apply_manim_ops(body, ops)
    assert result.ok
    assert "Text('Torque')" in result.artifact
    assert "Text('Hello')" not in result.artifact


def test_manim_replace_requires_unique_before():
    body = "Text('x')\nText('x')\n"
    ops = [RepairOp(target="construct_body", op="replace", before="Text('x')", after="Text('y')")]
    result = apply_manim_ops(body, ops)
    assert not result.ok
    assert result.failed


def test_remotion_set_fields_including_new_beats():
    spec = {"beat": "compare", "title": "Old", "bullets": ["a", "b"], "left_items": ["x"], "steps": []}
    ops = [
        RepairOp(target="title", op="set", value="New Title"),
        RepairOp(target="bullets[1]", op="set", value="second"),
        RepairOp(target="left_items[1]", op="set", value="y"),
        RepairOp(target="formula", op="set", value="τ = F × r"),
        RepairOp(target="steps", op="set", value=["one", "two"]),
    ]
    result = apply_remotion_ops(spec, ops)
    assert result.ok, result.failed
    assert result.artifact["title"] == "New Title"
    assert result.artifact["bullets"] == ["a", "second"]
    assert result.artifact["left_items"] == ["x", "y"]
    assert result.artifact["formula"] == "τ = F × r"
    assert result.artifact["steps"] == ["one", "two"]
    assert RemotionSpec.model_validate(result.artifact).beat == "compare"


def test_remotion_beat_cannot_be_changed_by_ops():
    result = apply_remotion_ops({"beat": "bullets", "title": "T"}, [RepairOp(target="beat", op="set", value="steps")])
    assert not result.ok and result.failed == ["set:beat:forbidden"]


def test_image_prompt_addendum():
    ops = [RepairOp(target="prompt_addendum", op="append_constraint", after="Keep all captions inside safe margins.")]
    assert "safe margins" in prompt_addendum_from_ops(ops)
    result = apply_image_ops("base prompt", ops)
    assert "CONSTRAINTS:" in result.artifact


def test_image_build_prompt_uses_repair():
    brief = SceneBrief(id="s6", title="Mistakes", scene_type=SceneType.IMAGE,
                       visual_brief="Three panels about torque mistakes")
    repair = SceneRepair(
        scene_id="s6", scene_type=SceneType.IMAGE, passed=False,
        ops=[RepairOp(target="prompt_addendum", op="append_constraint", after="Never clip panel captions.")],
    )
    prompt = image_adapter.build_prompt(brief, StyleConfig(), repair=repair)
    assert "Never clip panel captions." in prompt


def test_interactive_set_parameter():
    payload = {
        "template": "physics_lever",
        "parameters": {"default_weight_A": 10.0, "default_weight_B": 12.0},
        "instruction": "Balance the lever",
    }
    ops = [RepairOp(target="parameters.default_weight_A", op="set", value=8.0)]
    result = apply_interactive_ops(payload, ops)
    assert result.ok
    assert result.artifact["parameters"]["default_weight_A"] == 8.0
    assert result.artifact["parameters"]["default_weight_B"] == 12.0


def test_interactive_forbids_template_change():
    payload = {"template": "physics_lever", "parameters": {}, "instruction": ""}
    ops = [RepairOp(target="template", op="set", value="multiple_choice")]
    result = apply_interactive_ops(payload, ops)
    assert not result.ok


def test_scene_repair_needs_repair():
    passed = SceneRepair(passed=True, fix_action="noop", severity="minor")
    assert not passed.needs_repair()
    minor_fail = SceneRepair(passed=False, fix_action="noop", severity="minor")
    assert not minor_fail.needs_repair()
    major = SceneRepair(passed=False, fix_action="patch_artifact", severity="major")
    assert major.needs_repair()


def test_patch_is_not_repeated_after_a_failed_patch():
    from eduharness.schema import PreparedScene, SceneType
    from eduharness.stage2.repair_router import _may_patch

    repair = SceneRepair(passed=False, fix_action="patch_artifact", severity="major",
                         ops=[RepairOp(target="title", op="set", value="x")])
    fresh = PreparedScene(scene_id="s", scene_type=SceneType.REMOTION, debug={"repair_mode": "generated"})
    patched = PreparedScene(scene_id="s", scene_type=SceneType.REMOTION, debug={"repair_mode": "patched"})
    assert _may_patch(fresh, repair)
    assert not _may_patch(patched, repair)
    assert not _may_patch(fresh, SceneRepair(passed=False, fix_action="re_render", severity="major"))


def test_manim_placement_ops_rewrite_one_grid_line() -> None:
    """A spatial fix is one line: the reviewer names an object and a region, and the
    body comes back with that placement moved and everything else byte-identical."""
    from eduharness.stage2.repair_apply.manim_ops import (
        apply_manim_ops,
        grid_placements,
        position_table,
    )

    body = (
        "axes = self.axes()\n"
        "self.place_in_area(axes, 'A1', 'D4', scale_factor=0.9)\n"
        "note = label('DV = 2 V')\n"
        "self.place_at_grid(note, 'C3')\n"
        "self.wait(1)\n"
    )
    table = position_table(body)
    assert "| axes | place_in_area | A1-D4 | 0.9 | 2 |" in table
    assert "| note | place_at_grid | C3 | default | 4 |" in table

    result = apply_manim_ops(body, [
        RepairOp(target="note", op="set", value={"area": ["E5", "F6"]}, rationale="clears the brace"),
    ])
    assert result.ok, result.failed
    assert "self.place_in_area(note, 'E5', 'F6')" in result.artifact
    assert "self.place_in_area(axes, 'A1', 'D4', scale_factor=0.9)" in result.artifact
    assert result.artifact.splitlines()[0] == body.splitlines()[0]
    moved = {item.object_name: item.anchors for item in grid_placements(result.artifact)}
    assert moved["note"] == ("E5", "F6") and moved["axes"] == ("A1", "D4")


def test_manim_placement_ops_keep_scale_and_reject_nonsense() -> None:
    from eduharness.stage2.repair_apply.manim_ops import apply_manim_ops

    body = "self.place_at_grid(tag, 'B2', scale_factor=0.7)\n"
    kept = apply_manim_ops(body, [RepairOp(target="tag", op="set", value={"cell": "D5"})])
    assert kept.ok and "self.place_at_grid(tag, 'D5', scale_factor=0.7)" in kept.artifact

    rescaled = apply_manim_ops(body, [RepairOp(target="tag", op="set", value={"cell": "D5", "scale": 0.5})])
    assert rescaled.ok and "scale_factor=0.5" in rescaled.artifact

    off_grid = apply_manim_ops(body, [RepairOp(target="tag", op="set", value={"cell": "Z9"})])
    assert not off_grid.ok and any("bad-anchors" in f for f in off_grid.failed)

    unknown = apply_manim_ops(body, [RepairOp(target="ghost", op="set", value={"cell": "D5"})])
    assert not unknown.ok and any("not-placed-on-grid" in f for f in unknown.failed)


def test_manim_placements_may_patch_twice_but_body_edits_may_not() -> None:
    """Layout settles over passes — the second collision often only shows once the
    first is gone — so placement ops keep their cheap route; text edits do not."""
    from eduharness.schema import PreparedScene, SceneType
    from eduharness.stage2.repair_router import _may_patch

    patched = PreparedScene(scene_id="s", scene_type=SceneType.MANIM, debug={"repair_mode": "patched"})
    placement = SceneRepair(passed=False, fix_action="patch_artifact", severity="major",
                            ops=[RepairOp(target="note", op="set", value={"cell": "D5"})])
    body_edit = SceneRepair(passed=False, fix_action="patch_artifact", severity="major",
                            ops=[RepairOp(target="construct_body", op="replace", before="a", after="b")])
    assert _may_patch(patched, placement)
    assert not _may_patch(patched, body_edit)
