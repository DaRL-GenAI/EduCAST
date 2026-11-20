"""JSON field patches for Remotion beat specs."""

from __future__ import annotations

import re
from typing import Any

from ...schema import RepairOp
from .common import ApplyResult

STRING_FIELDS = {"title", "subtitle", "formula", "left_title", "right_title", "accent_label", "motion"}
LIST_FIELDS = {"bullets", "steps", "left_items", "right_items", "highlights"}
_INDEXED = re.compile(r"^(bullets|steps|left_items|right_items|highlights)\[(\d+)\]$")


def apply_remotion_ops(spec: dict[str, Any], ops: list[RepairOp]) -> ApplyResult:
    data = dict(spec)
    for key in LIST_FIELDS:
        if key in data and not isinstance(data[key], list):
            data[key] = list(data[key] or [])
    applied: list[str] = []
    failed: list[str] = []

    for op in ops:
        target = (op.target or "").strip()
        try:
            if target == "beat":
                failed.append("set:beat:forbidden")
                continue
            if op.op == "set":
                _set_target(data, target, op.value if op.value is not None else op.after)
                applied.append(f"set:{target}")
            elif op.op == "replace":
                _replace_target(data, target, op.before or "", op.after if op.after is not None else "")
                applied.append(f"replace:{target}")
            else:
                failed.append(f"{op.op}:{target}:unsupported-op")
        except Exception as exc:
            failed.append(f"{op.op}:{target}:{exc}")

    ok = bool(applied) and not failed
    return ApplyResult(
        ok=ok, artifact=data, applied=applied, failed=failed,
        mode="patched" if applied else "unchanged",
    )


def _set_target(data: dict[str, Any], target: str, value: Any) -> None:
    if target in STRING_FIELDS:
        data[target] = "" if value is None else str(value)
        return
    if target in LIST_FIELDS:
        if isinstance(value, list):
            data[target] = [str(x) for x in value]
        elif value is None:
            data[target] = []
        else:
            data[target] = [str(value)]
        return
    match = _INDEXED.match(target)
    if match:
        field, idx = match.group(1), int(match.group(2))
        items = list(data.get(field) or [])
        while len(items) <= idx:
            items.append("")
        items[idx] = "" if value is None else str(value)
        data[field] = items
        return
    raise ValueError(f"unsupported remotion target: {target}")


def _replace_target(data: dict[str, Any], target: str, before: str, after: str) -> None:
    if target in STRING_FIELDS:
        current = str(data.get(target, ""))
        if before and current.count(before) == 1:
            data[target] = current.replace(before, after, 1)
        elif not before:
            data[target] = after
        else:
            raise ValueError("before-mismatch")
        return
    match = _INDEXED.match(target)
    if match:
        field, idx = match.group(1), int(match.group(2))
        items = list(data.get(field) or [])
        if idx >= len(items):
            raise ValueError("index out of range")
        current = str(items[idx])
        if before and current.count(before) != 1:
            raise ValueError("before-mismatch")
        items[idx] = current.replace(before, after, 1) if before else after
        data[field] = items
        return
    if target in LIST_FIELDS:
        items = list(data.get(target) or [])
        joined = "\n".join(items)
        if before and joined.count(before) != 1:
            raise ValueError("before-mismatch")
        if before:
            data[target] = [line for line in joined.replace(before, after, 1).split("\n") if line != ""]
        else:
            data[target] = [after] if after else []
        return
    raise ValueError(f"unsupported remotion target: {target}")
