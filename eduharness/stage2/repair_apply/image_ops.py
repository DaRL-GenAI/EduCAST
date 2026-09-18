"""Prompt-constraint patches for image scenes."""

from __future__ import annotations

from ...schema import RepairOp
from .common import ApplyResult


def prompt_addendum_from_ops(ops: list[RepairOp]) -> str:
    chunks: list[str] = []
    for op in ops:
        target = (op.target or "").strip()
        if target != "prompt_addendum":
            continue
        if op.op == "append_constraint":
            text = op.after or (str(op.value) if op.value is not None else "")
            if text.strip():
                chunks.append(text.strip())
        elif op.op in {"set", "replace"}:
            text = op.after or (str(op.value) if op.value is not None else "")
            if text.strip():
                chunks.append(text.strip())
    return " ".join(chunks)


def apply_image_ops(base_prompt: str, ops: list[RepairOp]) -> ApplyResult:
    addendum = prompt_addendum_from_ops(ops)
    applied = [f"append_constraint:prompt_addendum"] if addendum else []
    failed = [
        f"{op.op}:{op.target}:unsupported"
        for op in ops
        if (op.target or "").strip() != "prompt_addendum"
    ]
    prompt = base_prompt
    if addendum:
        prompt = f"{base_prompt} CONSTRAINTS: {addendum}"
    ok = bool(addendum) and not failed
    return ApplyResult(
        ok=ok or (bool(addendum) and not ops),
        artifact=prompt,
        applied=applied,
        failed=failed,
        mode="patched" if addendum else "unchanged",
    )
