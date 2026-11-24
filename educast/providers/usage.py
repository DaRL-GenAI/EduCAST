"""Thread-safe API usage + cost ledger written to <run_dir>/usage.json."""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# USD per 1M tokens: (input, output). Unknown models fall back to "default".
TOKEN_PRICING_PER_M: dict[str, tuple[float, float]] = {
    "gpt-5": (1.25, 10.0),
    "gpt-5-mini": (0.25, 2.0),
    "gpt-5-nano": (0.05, 0.4),
    "gpt-5.1": (1.25, 10.0),
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.0, 8.0),
    "gpt-4.1-mini": (0.4, 1.6),
    "default": (2.5, 10.0),
}
TTS_PRICE_PER_1M_CHARS = 12.0
IMAGE_PRICE_DEFAULT = 0.08  # gpt-image-1 medium 1536x1024 (approx.)


def _price_for(model: str) -> tuple[float, float]:
    best = "default"
    for key in TOKEN_PRICING_PER_M:
        if key != "default" and model.startswith(key) and len(key) > len(best if best != "default" else ""):
            best = key
    return TOKEN_PRICING_PER_M[best]


@dataclass
class UsageEvent:
    kind: str  # chat | vision | image | tts
    model: str
    label: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    characters: int = 0
    images: int = 0
    seconds: float = 0.0
    cost_usd: float = 0.0
    at: float = field(default_factory=time.time)


class UsageTracker:
    def __init__(self, path: Path | None = None):
        self.path = path
        self.events: list[UsageEvent] = []
        self._lock = threading.Lock()
        self.write_error: str | None = None
        # Stages run as separate processes; keep one ledger per run directory.
        if path is not None and path.is_file():
            try:
                for raw in json.loads(path.read_text(encoding="utf-8")).get("events", []):
                    self.events.append(UsageEvent(**{k: v for k, v in raw.items() if k in UsageEvent.__dataclass_fields__}))
            except Exception:
                self.events = []

    # -- recording -----------------------------------------------------------------
    def record_tokens(
        self,
        kind: str,
        model: str,
        *,
        input_tokens: int,
        output_tokens: int,
        reasoning_tokens: int = 0,
        seconds: float = 0.0,
        label: str = "",
    ) -> UsageEvent:
        inp, out = _price_for(model)
        cost = input_tokens / 1e6 * inp + output_tokens / 1e6 * out
        return self._add(
            UsageEvent(
                kind=kind, model=model, label=label,
                input_tokens=input_tokens, output_tokens=output_tokens,
                reasoning_tokens=reasoning_tokens, seconds=seconds, cost_usd=cost,
            )
        )

    def record_image(self, model: str, *, seconds: float = 0.0, label: str = "") -> UsageEvent:
        return self._add(
            UsageEvent(kind="image", model=model, label=label, images=1,
                       seconds=seconds, cost_usd=IMAGE_PRICE_DEFAULT)
        )

    def record_tts(self, model: str, characters: int, *, seconds: float = 0.0, label: str = "") -> UsageEvent:
        return self._add(
            UsageEvent(kind="tts", model=model, label=label, characters=characters,
                       seconds=seconds, cost_usd=characters / 1e6 * TTS_PRICE_PER_1M_CHARS)
        )

    def _add(self, event: UsageEvent) -> UsageEvent:
        with self._lock:
            self.events.append(event)
            self._flush_locked()
        return event

    # -- reporting -----------------------------------------------------------------
    def summary(self) -> dict[str, Any]:
        by_kind: dict[str, dict[str, float]] = {}
        for e in self.events:
            bucket = by_kind.setdefault(
                e.kind, {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                         "reasoning_tokens": 0, "cost_usd": 0.0, "seconds": 0.0}
            )
            bucket["calls"] += 1
            bucket["input_tokens"] += e.input_tokens
            bucket["output_tokens"] += e.output_tokens
            bucket["reasoning_tokens"] += e.reasoning_tokens
            bucket["cost_usd"] += e.cost_usd
            bucket["seconds"] += e.seconds
        total = sum(e.cost_usd for e in self.events)
        return {
            "total_cost_usd": round(total, 4),
            "calls": len(self.events),
            "by_kind": {k: {kk: (round(vv, 4) if isinstance(vv, float) else vv) for kk, vv in v.items()}
                        for k, v in by_kind.items()},
        }

    def _flush_locked(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                {
                    "summary": self.summary(),
                    "events": [asdict(e) for e in self.events],
                },
                indent=2,
            )
            temp = self.path.with_suffix(self.path.suffix + ".tmp")
            temp.write_text(
                payload,
                encoding="utf-8",
            )
            os.replace(temp, self.path)
            self.write_error = None
        except OSError as exc:
            # The in-memory ledger remains usable, but callers can surface the
            # warning instead of presenting a silently incomplete cost total.
            self.write_error = str(exc)

    def format_summary(self) -> str:
        s = self.summary()
        parts = [f"${s['total_cost_usd']:.3f} over {s['calls']} calls"]
        for kind, v in s["by_kind"].items():
            parts.append(f"{kind}: {v['calls']}x ${v['cost_usd']:.3f}")
        return " | ".join(parts)
