"""Regressions for three defects that each made a scene unfixable by the loop.

1. Shared list clipping: every list field was trimmed to 5 while `left_items`,
   `right_items` cap at 3 and `highlights` at 4, so a model returning 4
   right_items raised a validation error and the scene never rendered at all.
2. `highlights` was declared in the renderer's props and drawn by nothing, so a
   key element asking for an emphasised term could never be satisfied.
3. `self.annotate` raised when no position was fully clear, which replaced the
   whole scene with a placeholder slide instead of reporting one bad label.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from eduharness.schema import StyleConfig
from eduharness.stage2.adapters import manim as manim_adapter
from eduharness.stage2.adapters.remotion import RemotionSpec, _list_cap

TEMPLATE = Path(__file__).resolve().parents[1] / "remotion_template" / "src" / "SceneBeat.tsx"


@pytest.mark.parametrize(
    "field, cap",
    [("bullets", 5), ("steps", 5), ("left_items", 3), ("right_items", 3), ("highlights", 4)],
)
def test_list_cap_matches_the_declared_maximum(field: str, cap: int) -> None:
    assert _list_cap(RemotionSpec, field) == cap


@pytest.mark.parametrize(
    "field, cap",
    [("bullets", 5), ("steps", 5), ("left_items", 3), ("right_items", 3), ("highlights", 4)],
)
def test_overlong_lists_are_clipped_not_rejected(field: str, cap: int) -> None:
    """A model that returns one item too many loses the item, not the scene."""
    spec = RemotionSpec(**{field: [f"item {i}" for i in range(cap + 3)]})
    assert len(getattr(spec, field)) == cap


def test_every_beat_field_the_prompt_advertises_is_drawn_by_the_renderer() -> None:
    """The executor prompt and the renderer must name the same fields.

    `recap` used to be advertised as two columns plus a highlighted formula card;
    the renderer joined bullets and formula into one block and drew neither the
    columns nor the highlights, so scenes could satisfy the prompt and still fail
    review for content that was never on screen.
    """
    source = TEMPLATE.read_text(encoding="utf-8")
    for field in ("bullets", "formula", "left_items", "right_items", "steps", "stats",
                  "subtitle", "accent_label", "highlights"):
        assert f"props.{field}" in source, f"{field} is declared but never drawn"


def test_highlights_reach_the_formula_and_the_recap_block() -> None:
    source = TEMPLATE.read_text(encoding="utf-8")
    assert source.count("highlight={props.highlights}") >= 2
    assert "function withHighlights(" in source


def test_annotate_degrades_instead_of_raising() -> None:
    """A crowded label is reported as a finding; the scene still renders."""
    header = manim_adapter.assemble_script("pass", StyleConfig(), "EduScene")
    ast.parse(header)  # the generated scene must stay valid Python
    assert "No clear nearby space" not in header, "the hard raise is back"
    assert "annotation_crowded" in header
    assert "_annotation_penalty" in header


def test_crowded_annotation_triggers_the_render_retry() -> None:
    """The regeneration the crash used to force is kept; the crash is not."""
    from eduharness.stage2 import workflow

    source = Path(workflow.__file__).read_text(encoding="utf-8")
    assert '"annotation_crowded"' in source


def test_interactive_scenes_are_reviewed_as_standalone_panels() -> None:
    """The renderer builds practice panels with an empty teaching_layout on purpose.

    Handing them the board contract made the reviewer ask a standalone panel for a
    title band, a lecture column and a right visual column it is designed not to
    have, so a scene lost points for following its own brief.
    """
    from eduharness.stage2 import reviewer

    source = Path(reviewer.__file__).read_text(encoding="utf-8")
    assert "scene.scene_type == SceneType.INTERACTIVE" in source
    contract = source.split("scene.scene_type == SceneType.INTERACTIVE", 1)[1][:900]
    assert "no title band" in contract and "no lecture column" in contract


def test_manim_subprocess_is_pinned_to_one_thread() -> None:
    """BLAS pools sized from the host core count starve a CPU-capped container.

    A pod limited to 14 CPUs still reports 128 cores, so each render spawned ~130
    threads and parallel scenes multiplied that into hundreds fighting over the
    quota -- a scene then crawls at single-digit CPU efficiency and times out.
    """
    from eduharness.stage2.adapters.manim import _restricted_env

    env = _restricted_env()
    for pool in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        assert env.get(pool) == "1", f"{pool} must be pinned for the render subprocess"


def test_fallback_slide_has_no_shadowing_local_pil_import() -> None:
    """The static-slide fallback must work for every beat, not just title_card.

    A `from PIL import Image, ImageDraw` inside the title_card branch made both
    names local to the whole function, so every other beat hit UnboundLocalError
    in the shared drawing code below it: "Remotion unavailable" became a failed
    scene instead of the still this function exists to produce.
    """
    import ast

    from eduharness.stage2.adapters import remotion as remotion_adapter

    tree = ast.parse(Path(remotion_adapter.__file__).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "render_fallback_slide")
    local_pil = [n for n in ast.walk(fn)
                 if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("PIL")]
    assert not local_pil, "a local PIL import shadows the module-level one for the whole function"


def test_every_guard_kind_the_scene_header_emits_is_accepted_by_the_schema() -> None:
    """A kind the header writes but GuardKind rejects poisons the whole report.

    Pydantic fails the entire GuardFinding list, the scene is reported as
    unchecked, and that is a blocker — strictly worse than the finding it was
    trying to report.
    """
    import re

    from eduharness.schema import GuardFinding, StyleConfig
    from eduharness.stage2.adapters.manim import assemble_script

    header = assemble_script("pass", StyleConfig(), "EduScene")
    emitted = set(re.findall(r"self\._add\(\s*['\"]([a-z_]+)['\"]", header))
    assert emitted, "no guard kinds found in the generated header"
    for kind in emitted:
        GuardFinding(kind=kind, message="x")  # raises if the Literal rejects it


def test_board_cards_are_opaque_so_the_character_cannot_show_through() -> None:
    """A 4%-alpha card let the corner character show through the takeaway card.

    Every reviewer read that as "the character overlaps the takeaway card" and
    scored it a blocking layout defect on otherwise clean recap scenes -- across
    two different lessons.
    """
    source = TEMPLATE.read_text(encoding="utf-8")
    card = source.split("function Card(", 1)[1].split("function ", 1)[0]
    assert "backgroundColor: t.bg" in card, "the card must paint an opaque base"
    assert "linear-gradient" in card, "the accent tint should survive the opaque base"
