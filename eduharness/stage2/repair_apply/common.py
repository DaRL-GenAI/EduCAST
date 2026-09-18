"""Shared apply result for tool patchers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ApplyResult:
    ok: bool
    artifact: Any = None
    applied: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    mode: str = "unchanged"  # patched | targeted_regen | skipped | unchanged

    @property
    def partial(self) -> bool:
        return bool(self.applied) and bool(self.failed)
