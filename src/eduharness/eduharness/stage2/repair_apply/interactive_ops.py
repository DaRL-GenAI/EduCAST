"""JSON path patches for interactive template parameters."""

from __future__ import annotations

from typing import Any

from ...schema import RepairOp
from .common import ApplyResult


def apply_interactive_ops(payload: dict[str, Any], ops: list[RepairOp]) -> ApplyResult:
    data = {
        "template": payload.get("template"),
        "parameters": dict(payload.get("parameters") or {}),
        "instruction": payload.get("instruction") or "",
        "success_condition": payload.get("success_condition"),
    }
    applied: list[str] = []
    failed: list[str] = []

    for op in ops:
        target = (op.target or "").strip()
        if op.op != "set":
            failed.append(f"{op.op}:{target}:unsupported-op")
            continue
        value = op.value if op.value is not None else op.after
        try:
            if target == "instruction":
                data["instruction"] = "" if value is None else str(value)
                applied.append(f"set:{target}")
            elif target.startswith("parameters."):
                key = target[len("parameters.") :].strip()
                if not key or "." in key:
                    raise ValueError("only one-level parameters.<key> supported")
                data["parameters"][key] = value
                applied.append(f"set:{target}")
            elif target == "template":
                failed.append(f"set:template:forbidden")
            else:
                failed.append(f"set:{target}:unsupported-target")
        except Exception as exc:
            failed.append(f"set:{target}:{exc}")

    ok = bool(applied) and not failed
    return ApplyResult(
        ok=ok,
        artifact=data,
        applied=applied,
        failed=failed,
        mode="patched" if applied else "unchanged",
    )
