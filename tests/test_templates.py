from __future__ import annotations

import pytest
from pydantic import ValidationError

from eduharness.schema import InteractiveParams, Palette, StyleConfig
from eduharness.templates.registry import (
    list_templates,
    load_template,
    normalize_params,
    catalog_for_prompt,
)


@pytest.mark.parametrize("template_id", list_templates())
def test_template_defaults_are_valid(template_id: str) -> None:
    params, warnings = normalize_params(template_id, load_template(template_id).defaults)
    assert params
    assert warnings == []


def test_catalog_mentions_every_template() -> None:
    text = catalog_for_prompt()
    for tid in list_templates():
        assert f"- {tid}:" in text


def test_multiple_choice_invalid_index_falls_back_atomically() -> None:
    params, warnings = normalize_params(
        "multiple_choice",
        {"choices": ["A", "B"], "correct_index": 99, "question": "Q"},
    )
    assert params["correct_index"] == 0
    assert params["choices"] == ["Option A", "Option B", "Option C", "Option D"]
    assert warnings and "defaults restored" in warnings[0]


def test_unknown_parameter_is_dropped_not_fatal() -> None:
    params, warnings = normalize_params(
        "multiple_choice",
        {"question": "Q", "choices": ["A", "B"], "correct_index": 1, "shuffle": True},
    )
    assert params["correct_index"] == 1
    assert warnings and "Dropped unknown parameters" in warnings[0]


def test_drag_sort_requires_same_multiset_and_shuffled_start() -> None:
    params, warnings = normalize_params(
        "drag_sort",
        {"items": ["A", "B"], "correct_order": ["A", "C"], "prompt": "Order"},
    )
    assert params["correct_order"] == ["Step A", "Step B", "Step C"]
    assert warnings
    _, warnings = normalize_params(
        "drag_sort",
        {"items": ["A", "B"], "correct_order": ["A", "B"], "prompt": "Order"},
    )
    assert warnings  # already sorted → rejected


def test_number_line_repairs_invalid_range() -> None:
    params, warnings = normalize_params(
        "number_line",
        {"prompt": "Place", "min": 10, "max": 0, "target": 5, "tolerance": 1},
    )
    assert params["min"] < params["max"]
    assert warnings


def test_fill_blank_accepts_alternatives_in_answer() -> None:
    params, warnings = normalize_params(
        "fill_blank",
        {"prompt": "Torque is ___ times ___.", "blanks": [
            {"label": "a", "answer": "force|weight"}, {"label": "b", "answer": "distance"}]},
    )
    assert warnings == []
    assert params["blanks"][0]["answer"] == "force|weight"


def test_legacy_success_condition_migrates_without_eval() -> None:
    value = InteractiveParams(
        template="multiple_choice",
        parameters={},
        success_condition="student selects answer",
    )
    assert value.success_condition.kind == "template_default"
    assert value.success_condition.description == "student selects answer"


def test_style_rejects_injection_like_values() -> None:
    with pytest.raises(ValidationError):
        StyleConfig(palette=Palette(primary="red; background:url(x)"))
    with pytest.raises(ValidationError):
        StyleConfig.model_validate({"typography": {"font_family": 'Arial";color:red'}})


def test_physics_lever_defaults_are_not_balanced() -> None:
    params, warnings = normalize_params("physics_lever", {})
    assert warnings == []
    left = params["default_weight_A"] * params["default_distance_A"]
    right = params["default_weight_B"] * params["default_distance_B"]
    assert abs(left - right) > params["tolerance"]


def test_physics_lever_rejects_balanced_start_and_bad_distance() -> None:
    _, warnings = normalize_params("physics_lever", {
        "default_weight_A": 10, "default_weight_B": 10, "default_distance_A": 0.5,
        "default_distance_B": 0.5, "instruction": "Balance it",
    })
    assert warnings
    _, warnings = normalize_params("physics_lever", {
        "default_weight_A": 10, "default_weight_B": 20, "default_distance_A": 3.0,
        "default_distance_B": 0.5, "max_distance": 1.0, "instruction": "Balance it",
    })
    assert warnings
