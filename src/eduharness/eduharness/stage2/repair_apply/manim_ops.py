"""Patches for Manim construct bodies: exact-text edits and grid placements.

The grid path is the one that fixes layout. A construct body places objects with
``self.place_at_grid(obj, 'B2')`` / ``self.place_in_area(obj, 'A1', 'C3')``, so a
spatial defect is one line and one pair of anchors — a reviewer that answers with
"put `text_h2` in C2-D3" produces a patch, where a prose complaint produces a
rewrite of the whole scene and a fresh set of collisions. (The approach is
Code2Video's: extract a position table, let the critic answer in anchors, rewrite
that line.)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ...schema import RepairOp
from ..adapters import manim as manim_adapter
from .common import ApplyResult


_CELL = r"[A-F][1-6]"
_AT_GRID = re.compile(
    rf"""self\.place_at_grid\(\s*(?P<obj>[A-Za-z_]\w*)\s*,\s*['"](?P<cell>{_CELL})['"]"""
    r"""(?:\s*,\s*scale_factor\s*=\s*(?P<scale>[0-9.]+))?\s*\)"""
)
_IN_AREA = re.compile(
    rf"""self\.place_in_area\(\s*(?P<obj>[A-Za-z_]\w*)\s*,\s*['"](?P<top_left>{_CELL})['"]\s*,"""
    rf"""\s*['"](?P<bottom_right>{_CELL})['"]"""
    r"""(?:\s*,\s*scale_factor\s*=\s*(?P<scale>[0-9.]+))?\s*\)"""
)


@dataclass
class GridPlacement:
    """One placement call found in a construct body."""

    object_name: str
    method: str          # place_at_grid | place_in_area
    anchors: tuple[str, ...]
    scale: float | None
    line_number: int     # 1-based, within the construct body
    source: str


def grid_placements(construct_body: str) -> list[GridPlacement]:
    """Every grid placement in the body, in source order."""
    found: list[GridPlacement] = []
    for number, line in enumerate(construct_body.splitlines(), 1):
        at_grid = _AT_GRID.search(line)
        if at_grid:
            found.append(GridPlacement(
                object_name=at_grid.group("obj"), method="place_at_grid",
                anchors=(at_grid.group("cell"),),
                scale=float(at_grid.group("scale")) if at_grid.group("scale") else None,
                line_number=number, source=line.strip(),
            ))
        in_area = _IN_AREA.search(line)
        if in_area:
            found.append(GridPlacement(
                object_name=in_area.group("obj"), method="place_in_area",
                anchors=(in_area.group("top_left"), in_area.group("bottom_right")),
                scale=float(in_area.group("scale")) if in_area.group("scale") else None,
                line_number=number, source=line.strip(),
            ))
    return found


def position_table(construct_body: str) -> str:
    """The placement table handed to the reviewer, so it can answer in anchors."""
    placements = grid_placements(construct_body)
    if not placements:
        return "(this scene places nothing on the grid)"
    rows = ["| object | method | anchors | scale | line |",
            "|---|---|---|---|---|"]
    for item in placements:
        rows.append(f"| {item.object_name} | {item.method} | {'-'.join(item.anchors)} "
                    f"| {item.scale if item.scale is not None else 'default'} | {item.line_number} |")
    return "\n".join(rows)


def _anchors_of(value) -> list[str]:
    if isinstance(value, str):
        return [part for part in re.split(r"[-,\s]+", value.strip().upper()) if part]
    if isinstance(value, (list, tuple)):
        return [str(part).strip().upper() for part in value if str(part).strip()]
    if isinstance(value, dict):
        for key in ("area", "anchors", "cell", "position", "to"):
            if key in value:
                return _anchors_of(value[key])
    return []


def _scale_of(value) -> float | None:
    if isinstance(value, dict):
        raw = value.get("scale", value.get("scale_factor"))
        if raw is not None:
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None
    return None


def _rewrite_placement(body: str, placement: GridPlacement, anchors: list[str],
                       scale: float | None) -> str | None:
    """Return the body with this placement moved to `anchors` (None when unusable)."""
    if not all(re.fullmatch(_CELL, anchor) for anchor in anchors) or len(anchors) not in (1, 2):
        return None
    keep = placement.scale if scale is None else scale
    tail = f", scale_factor={keep}" if keep is not None else ""
    if len(anchors) == 1:
        call = f"self.place_at_grid({placement.object_name}, '{anchors[0]}'{tail})"
    else:
        call = (f"self.place_in_area({placement.object_name}, "
                f"'{anchors[0]}', '{anchors[1]}'{tail})")
    lines = body.splitlines()
    index = placement.line_number - 1
    if not (0 <= index < len(lines)):
        return None
    original = lines[index]
    pattern = _AT_GRID if placement.method == "place_at_grid" else _IN_AREA
    match = pattern.search(original)
    if not match:
        return None
    lines[index] = original[:match.start()] + call + original[match.end():]
    return "\n".join(lines) + ("\n" if body.endswith("\n") else "")


def apply_manim_ops(construct_body: str, ops: list[RepairOp]) -> ApplyResult:
    body = construct_body
    applied: list[str] = []
    failed: list[str] = []
    for op in ops:
        target = (op.target or "construct_body").strip()

        if op.op in {"set", "replace"} and target not in {"construct_body", "body"}:
            # A grid op: the target names an object the scene placed.
            placements = [item for item in grid_placements(body) if item.object_name == target]
            if not placements:
                failed.append(f"{op.op}:{target}:not-placed-on-grid")
                continue
            anchors = _anchors_of(op.value) or _anchors_of(op.after)
            if not anchors:
                failed.append(f"{op.op}:{target}:no-anchors")
                continue
            candidate = _rewrite_placement(body, placements[-1], anchors, _scale_of(op.value))
            if candidate is None:
                failed.append(f"{op.op}:{target}:bad-anchors:{'-'.join(anchors)}")
                continue
            try:
                manim_adapter.validate_construct_body(candidate)
            except ValueError as exc:
                failed.append(f"{op.op}:{target}:validate:{exc}")
                continue
            body = candidate
            applied.append(f"place:{target}->{'-'.join(anchors)}")
            continue

        if target not in {"construct_body", "body"}:
            failed.append(f"{op.op}:{target}:unsupported-target")
            continue
        if op.op == "replace":
            before = op.before or ""
            after = op.after if op.after is not None else ""
            if not before:
                failed.append(f"replace:{target}:empty-before")
                continue
            count = body.count(before)
            if count != 1:
                failed.append(f"replace:{target}:before-count={count}")
                continue
            candidate = body.replace(before, after, 1)
            try:
                manim_adapter.validate_construct_body(candidate)
            except ValueError as exc:
                failed.append(f"replace:{target}:validate:{exc}")
                continue
            body = candidate
            applied.append(f"replace:{target}")
        else:
            failed.append(f"{op.op}:{target}:unsupported-op")
    ok = bool(applied) and not failed
    return ApplyResult(
        ok=ok,
        artifact=body,
        applied=applied,
        failed=failed,
        mode="patched" if applied else "unchanged",
    )
