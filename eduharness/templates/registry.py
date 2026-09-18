"""Parameterized interactive template registry.

Executor Agent may ONLY fill parameters — never invent new templates. Every
template has a trusted Pydantic model; invalid AI output falls back to the
template defaults atomically (and the fallback is reported as a warning).
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)


SCHEMAS_DIR = Path(__file__).parent / "schemas"


class TemplateSpec(BaseModel):
    id: str
    title: str
    description: str
    parameters_schema: dict[str, Any] = Field(default_factory=dict)
    defaults: dict[str, Any] = Field(default_factory=dict)
    success_hint: str = ""


ShortText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)
]
Hint = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]


class _ParamsBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PhysicsLeverParams(_ParamsBase):
    """Two weights on a beam; torque = weight × distance from the fulcrum."""

    default_weight_A: float = Field(ge=1, le=50)
    default_weight_B: float = Field(ge=1, le=50)
    default_distance_A: float = Field(0.6, gt=0, le=5)
    default_distance_B: float = Field(0.6, gt=0, le=5)
    max_distance: float = Field(1.0, gt=0, le=5)
    fulcrum_offset: float = Field(0.0, ge=-0.5, le=0.5)
    target_balance: bool = True
    tolerance: float = Field(0.5, gt=0, le=10)
    allow_distance: bool = True
    instruction: ShortText
    hint: Hint = ""

    @model_validator(mode="after")
    def sane_geometry(self) -> "PhysicsLeverParams":
        if self.default_distance_A > self.max_distance or self.default_distance_B > self.max_distance:
            raise ValueError("default distances must not exceed max_distance")
        if self.target_balance:
            left = self.default_weight_A * self.default_distance_A
            right = self.default_weight_B * self.default_distance_B
            if abs(left - right) <= self.tolerance:
                raise ValueError("initial state must be unbalanced when target_balance is true")
        return self


class MultipleChoiceParams(_ParamsBase):
    question: ShortText
    choices: list[ShortText] = Field(min_length=2, max_length=6)
    correct_index: int = Field(ge=0)
    explanation: str = Field(default="", max_length=500)
    hint: Hint = ""

    @model_validator(mode="after")
    def answer_exists(self) -> "MultipleChoiceParams":
        if self.correct_index >= len(self.choices):
            raise ValueError("correct_index must refer to a choice")
        if len(set(c.lower() for c in self.choices)) != len(self.choices):
            raise ValueError("choices must be distinct")
        return self


class DragSortParams(_ParamsBase):
    prompt: ShortText
    items: list[ShortText] = Field(min_length=2, max_length=8)
    correct_order: list[ShortText] = Field(min_length=2, max_length=8)
    hint: Hint = ""

    @model_validator(mode="after")
    def same_items(self) -> "DragSortParams":
        if Counter(self.items) != Counter(self.correct_order):
            raise ValueError("correct_order must contain the same items")
        if self.items == self.correct_order:
            raise ValueError("items must start shuffled (not already in the correct order)")
        return self


class BlankSpec(_ParamsBase):
    label: ShortText
    answer: ShortText  # alternatives separated by "|"


class FillBlankParams(_ParamsBase):
    prompt: ShortText
    blanks: list[BlankSpec] = Field(min_length=1, max_length=6)
    hint: Hint = ""


class NumberLineParams(_ParamsBase):
    prompt: ShortText
    min: float
    max: float
    target: float
    tolerance: float = Field(gt=0)
    unit: str = Field(default="", max_length=12)
    hint: Hint = ""

    @model_validator(mode="after")
    def valid_range(self) -> "NumberLineParams":
        if self.min >= self.max:
            raise ValueError("min must be less than max")
        if not self.min <= self.target <= self.max:
            raise ValueError("target must be inside the range")
        if self.tolerance > (self.max - self.min) / 4:
            raise ValueError("tolerance must be at most a quarter of the range")
        return self


PARAM_MODELS: dict[str, type[_ParamsBase]] = {
    "physics_lever": PhysicsLeverParams,
    "multiple_choice": MultipleChoiceParams,
    "drag_sort": DragSortParams,
    "fill_blank": FillBlankParams,
    "number_line": NumberLineParams,
}


def list_templates() -> list[str]:
    return sorted(p.stem for p in SCHEMAS_DIR.glob("*.json"))


def load_template(template_id: str) -> TemplateSpec:
    path = SCHEMAS_DIR / f"{template_id}.json"
    if not path.is_file():
        raise KeyError(f"Unknown template: {template_id}. Available: {list_templates()}")
    data = json.loads(path.read_text(encoding="utf-8"))
    spec = TemplateSpec.model_validate(data)
    spec.parameters_schema = PARAM_MODELS[template_id].model_json_schema()
    return spec


def merge_params(template_id: str, params: dict[str, Any]) -> dict[str, Any]:
    """Normalize AI params against a trusted per-template Pydantic model."""
    normalized, _ = normalize_params(template_id, params)
    return normalized


def normalize_params(
    template_id: str, params: dict[str, Any] | None
) -> tuple[dict[str, Any], list[str]]:
    """Return safe parameters and warnings; invalid output falls back atomically."""
    spec = load_template(template_id)
    incoming = {k: v for k, v in (params or {}).items() if v is not None}
    merged = {**spec.defaults, **incoming}
    model = PARAM_MODELS[template_id]
    try:
        return model.model_validate(merged).model_dump(), []
    except ValidationError as exc:
        # Drop unknown keys first — the most common model slip — and retry once.
        allowed = set(model.model_fields)
        trimmed = {k: v for k, v in merged.items() if k in allowed}
        if trimmed != merged:
            try:
                return model.model_validate(trimmed).model_dump(), [
                    f"Dropped unknown parameters: {sorted(set(merged) - allowed)}"
                ]
            except ValidationError as exc2:
                exc = exc2
        warning = f"Invalid generated parameters; defaults restored: {exc}"
        safe = model.model_validate(spec.defaults).model_dump()
        return safe, [warning]


def success_condition_for(template_id: str) -> dict[str, Literal["template_default"] | str]:
    spec = load_template(template_id)
    return {"kind": "template_default", "description": spec.success_hint}


def catalog_for_prompt() -> str:
    lines = []
    for tid in list_templates():
        spec = load_template(tid)
        raw = json.loads((SCHEMAS_DIR / f"{tid}.json").read_text(encoding="utf-8"))
        lines.append(f"- {spec.id}: {spec.description}")
        lines.append(f"  parameters={json.dumps(raw.get('parameters_schema', {}), ensure_ascii=False)}")
        lines.append(f"  defaults={json.dumps(spec.defaults, ensure_ascii=False)}")
        lines.append(f"  success={spec.success_hint}")
    return "\n".join(lines)
