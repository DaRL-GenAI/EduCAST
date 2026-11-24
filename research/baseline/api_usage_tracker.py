"""Track OpenAI API usage and estimated cost (Colab notebooks)."""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# USD per 1M tokens: (input, output)
TOKEN_PRICING_PER_M: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o-mini-tts": (0.60, 0.0),
    "gpt-5": (1.25, 10.0),
    "gpt-5.2": (1.75, 14.0),
    "o1": (15.0, 60.0),
    "o3": (2.0, 8.0),
    "whisper-1": (0.0, 0.0),
    "default": (2.5, 10.0),
}

# Flat per-unit costs (USD)
TTS_PRICE_PER_1M_CHARS = float(os.environ.get("API_TTS_PRICE_PER_1M_CHARS", "12.0"))
WHISPER_PRICE_PER_MINUTE = float(os.environ.get("API_WHISPER_PRICE_PER_MINUTE", "0.006"))
IMAGE_PRICE_DEFAULT = float(os.environ.get("API_IMAGE_PRICE_DEFAULT", "0.08"))


@dataclass
class UsageSnapshot:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    requests: int = 0
    tts_characters: int = 0
    whisper_calls: int = 0
    images_generated: int = 0
    estimated_cost_usd: float = 0.0
    by_model: dict[str, dict[str, float | int]] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["estimated_cost_usd"] = round(self.estimated_cost_usd, 6)
        return data


class UsageTracker:
    def __init__(self, usage_file: Path | None = None) -> None:
        self.usage_file = usage_file
        self._lock = threading.Lock()
        self._snapshot = UsageSnapshot()
        self._last_logged_cost = -1.0
        if usage_file is not None:
            existing = load_usage_file(usage_file)
            if existing:
                self._snapshot = UsageSnapshot(
                    prompt_tokens=int(existing.get("prompt_tokens", 0) or 0),
                    completion_tokens=int(existing.get("completion_tokens", 0) or 0),
                    total_tokens=int(existing.get("total_tokens", 0) or 0),
                    requests=int(existing.get("requests", 0) or 0),
                    tts_characters=int(existing.get("tts_characters", 0) or 0),
                    whisper_calls=int(existing.get("whisper_calls", 0) or 0),
                    images_generated=int(existing.get("images_generated", 0) or 0),
                    estimated_cost_usd=float(existing.get("estimated_cost_usd", 0) or 0),
                    by_model=dict(existing.get("by_model", {}) or {}),
                    updated_at=float(existing.get("updated_at", time.time()) or time.time()),
                )
                self._last_logged_cost = self._snapshot.estimated_cost_usd

    def _model_rates(self, model: str) -> tuple[float, float]:
        key = (model or "default").lower()
        for name, rates in TOKEN_PRICING_PER_M.items():
            if key == name or key.startswith(name):
                return rates
        return TOKEN_PRICING_PER_M["default"]

    def _bump_model(
        self,
        model: str,
        *,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_usd: float = 0.0,
        extra: dict[str, float | int] | None = None,
    ) -> None:
        bucket = self._snapshot.by_model.setdefault(
            model,
            {
                "requests": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "cost_usd": 0.0,
            },
        )
        bucket["requests"] = int(bucket["requests"]) + 1
        bucket["prompt_tokens"] = int(bucket["prompt_tokens"]) + prompt_tokens
        bucket["completion_tokens"] = int(bucket["completion_tokens"]) + completion_tokens
        bucket["cost_usd"] = round(float(bucket["cost_usd"]) + cost_usd, 6)
        if extra:
            for k, v in extra.items():
                bucket[k] = int(bucket.get(k, 0)) + int(v)

    def record_chat(self, model: str, usage: Any) -> None:
        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion = int(getattr(usage, "completion_tokens", 0) or 0)
        total = int(getattr(usage, "total_tokens", 0) or (prompt + completion))
        in_rate, out_rate = self._model_rates(model)
        cost = (prompt / 1_000_000) * in_rate + (completion / 1_000_000) * out_rate

        with self._lock:
            self._snapshot.requests += 1
            self._snapshot.prompt_tokens += prompt
            self._snapshot.completion_tokens += completion
            self._snapshot.total_tokens += total
            self._snapshot.estimated_cost_usd += cost
            self._snapshot.updated_at = time.time()
            self._bump_model(
                model,
                prompt_tokens=prompt,
                completion_tokens=completion,
                cost_usd=cost,
            )
        self._persist_and_log()

    def record_tts(self, model: str, text: str) -> None:
        chars = len(text or "")
        cost = (chars / 1_000_000) * TTS_PRICE_PER_1M_CHARS
        with self._lock:
            self._snapshot.requests += 1
            self._snapshot.tts_characters += chars
            self._snapshot.estimated_cost_usd += cost
            self._snapshot.updated_at = time.time()
            self._bump_model(model, cost_usd=cost, extra={"tts_characters": chars})
        self._persist_and_log()

    def record_whisper(self, model: str) -> None:
        # Duration unknown without parsing audio; use a small per-call estimate.
        cost = WHISPER_PRICE_PER_MINUTE * 0.25
        with self._lock:
            self._snapshot.requests += 1
            self._snapshot.whisper_calls += 1
            self._snapshot.estimated_cost_usd += cost
            self._snapshot.updated_at = time.time()
            self._bump_model(model, cost_usd=cost, extra={"whisper_calls": 1})
        self._persist_and_log()

    def record_image(self, model: str, *, count: int = 1, quality: str = "") -> None:
        unit = IMAGE_PRICE_DEFAULT * (2.0 if quality == "high" else 1.0)
        cost = unit * count
        with self._lock:
            self._snapshot.requests += 1
            self._snapshot.images_generated += count
            self._snapshot.estimated_cost_usd += cost
            self._snapshot.updated_at = time.time()
            self._bump_model(model, cost_usd=cost, extra={"images_generated": count})
        self._persist_and_log()

    def snapshot(self) -> UsageSnapshot:
        with self._lock:
            return UsageSnapshot(
                prompt_tokens=self._snapshot.prompt_tokens,
                completion_tokens=self._snapshot.completion_tokens,
                total_tokens=self._snapshot.total_tokens,
                requests=self._snapshot.requests,
                tts_characters=self._snapshot.tts_characters,
                whisper_calls=self._snapshot.whisper_calls,
                images_generated=self._snapshot.images_generated,
                estimated_cost_usd=round(self._snapshot.estimated_cost_usd, 6),
                by_model=json.loads(json.dumps(self._snapshot.by_model)),
                updated_at=self._snapshot.updated_at,
            )

    def _persist_and_log(self) -> None:
        snap = self.snapshot()
        if self.usage_file is not None:
            self.usage_file.parent.mkdir(parents=True, exist_ok=True)
            self.usage_file.write_text(
                json.dumps(snap.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        cost = snap.estimated_cost_usd
        if abs(cost - self._last_logged_cost) >= 0.0005:
            self._last_logged_cost = cost
            print(
                f"[usage] est. ${cost:.4f} | tokens {snap.total_tokens:,} "
                f"(in {snap.prompt_tokens:,} / out {snap.completion_tokens:,}) | "
                f"requests {snap.requests}",
                flush=True,
            )


_TRACKER: UsageTracker | None = None


def get_tracker() -> UsageTracker | None:
    return _TRACKER


def install_openai_usage_tracker(usage_file: Path | None = None) -> UsageTracker:
    """Monkey-patch OpenAI client methods to accumulate usage for the current job."""
    global _TRACKER
    if _TRACKER is not None:
        return _TRACKER

    from openai import OpenAI

    _TRACKER = UsageTracker(usage_file)

    if getattr(OpenAI, "_educast_usage_patched", False):
        return _TRACKER

    original_init = OpenAI.__init__

    def patched_init(self, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        _wrap_client(self, _TRACKER)

    OpenAI.__init__ = patched_init  # type: ignore[method-assign]
    OpenAI._educast_usage_patched = True
    return _TRACKER


def _wrap_client(client: Any, tracker: UsageTracker) -> None:
    if getattr(client, "_educast_wrapped", False):
        return
    client._educast_wrapped = True

    chat_create = client.chat.completions.create

    def wrapped_chat_create(*args: Any, **kwargs: Any) -> Any:
        resp = chat_create(*args, **kwargs)
        model = kwargs.get("model") or getattr(resp, "model", "unknown")
        usage = getattr(resp, "usage", None)
        if usage is not None:
            tracker.record_chat(str(model), usage)
        return resp

    client.chat.completions.create = wrapped_chat_create  # type: ignore[method-assign]

    speech_create = client.audio.speech.create

    def wrapped_speech_create(*args: Any, **kwargs: Any) -> Any:
        model = str(kwargs.get("model", "tts"))
        text = str(kwargs.get("input", ""))
        tracker.record_tts(model, text)
        return speech_create(*args, **kwargs)

    client.audio.speech.create = wrapped_speech_create  # type: ignore[method-assign]

    transcribe_create = client.audio.transcriptions.create

    def wrapped_transcribe_create(*args: Any, **kwargs: Any) -> Any:
        model = str(kwargs.get("model", "whisper-1"))
        tracker.record_whisper(model)
        return transcribe_create(*args, **kwargs)

    client.audio.transcriptions.create = wrapped_transcribe_create  # type: ignore[method-assign]

    images_generate = client.images.generate

    def wrapped_images_generate(*args: Any, **kwargs: Any) -> Any:
        model = str(kwargs.get("model", "image"))
        count = int(kwargs.get("n", 1) or 1)
        quality = str(kwargs.get("quality", ""))
        tracker.record_image(model, count=count, quality=quality)
        return images_generate(*args, **kwargs)

    client.images.generate = wrapped_images_generate  # type: ignore[method-assign]


def load_usage_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
