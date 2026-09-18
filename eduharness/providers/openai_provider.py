"""OpenAI backend — gpt-5 for text/vision, gpt-image for stills, TTS for narration.

Every call is metered into `UsageTracker` (tokens, images, characters, USD).
"""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any, Type, TypeVar

from pydantic import BaseModel, ValidationError

from ..config import Config, _env_float
from .usage import UsageTracker

T = TypeVar("T", bound=BaseModel)

_TRANSIENT = (
    "APIConnectionError",
    "RateLimitError",
    "APITimeoutError",
    "InternalServerError",
    "RemoteProtocolError",
    # Relays in front of the API surface 502/503/504 as a plain status error.
    "APIStatusError",
    "BadGateway",
    "ServiceUnavailable",
    "GatewayTimeout",
)


class OpenAIProvider:
    def __init__(self, cfg: Config, usage: UsageTracker | None = None):
        from openai import OpenAI

        self.cfg = cfg
        self.m = cfg.models
        default_base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        text_base = self.m.text_base_url or default_base
        media_base = self.m.media_base_url or default_base
        text_key = self.m.text_api_key or cfg.api_key
        media_key = self.m.media_api_key or cfg.api_key
        # A reasoning model planning a whole lesson can sit well past three
        # minutes, and the retry loop below then spends 3 x timeout before
        # surfacing anything -- so make the ceiling tunable like every other
        # knob rather than hard-coding the one value a slow model needs.
        timeout = _env_float("EDUHARNESS_REQUEST_TIMEOUT", 180.0)
        # chat/vision client (may be a company relay) and image/TTS client (official API)
        self.client = OpenAI(api_key=text_key, base_url=text_base, timeout=timeout, max_retries=0)
        self.media_client = (
            self.client if (media_base == text_base and media_key == text_key)
            else OpenAI(api_key=media_key, base_url=media_base, timeout=timeout, max_retries=0)
        )
        self.usage = usage or UsageTracker(cfg.usage_path)
        self._json_schema_supported = True

    # ------------------------------------------------------------------ text
    def chat(
        self,
        prompt: str,
        *,
        system: str = "",
        max_tokens: int = 4000,
        model: str | None = None,
        effort: str | None = None,
    ) -> str:
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = self._create(
            model=model or self.m.text, messages=messages, max_tokens=max_tokens,
            effort=effort, label="chat",
        )
        return _content(resp).strip()

    def chat_json(
        self,
        prompt: str,
        schema: Type[T],
        *,
        system: str = "",
        max_tokens: int = 4000,
        model: str | None = None,
        effort: str | None = None,
    ) -> T:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _json_system(system, schema)},
            {"role": "user", "content": prompt},
        ]
        return self._json_loop(
            messages, schema, model=model or self.m.text, max_tokens=max_tokens,
            effort=effort, label=f"chat_json:{schema.__name__}",
        )

    # ------------------------------------------------------------------ vision
    def vision(
        self,
        prompt: str,
        image_paths: list[str],
        *,
        system: str = "",
        max_tokens: int = 2000,
        effort: str | None = None,
    ) -> str:
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": _image_content(prompt, image_paths, self.cfg.vision_detail)})
        resp = self._create(
            model=self.m.vision, messages=messages, max_tokens=max_tokens,
            effort=effort, label="vision",
        )
        return _content(resp).strip()

    def vision_json(
        self,
        prompt: str,
        image_paths: list[str],
        schema: Type[T],
        *,
        system: str = "",
        max_tokens: int = 2000,
        effort: str | None = None,
    ) -> T:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _json_system(system, schema)},
            {"role": "user", "content": _image_content(prompt, image_paths, self.cfg.vision_detail)},
        ]
        return self._json_loop(
            messages, schema, model=self.m.vision, max_tokens=max_tokens,
            effort=effort, label=f"vision_json:{schema.__name__}",
        )

    # ------------------------------------------------------------------ media
    def image(self, prompt: str, out_path: str, *, size: str = "1536x1024") -> str:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        started = time.time()
        kwargs: dict[str, Any] = {"model": self.m.image, "prompt": prompt, "size": size, "n": 1}
        quality = os.environ.get("EDUHARNESS_IMAGE_QUALITY", "high")
        if self.m.image.startswith("gpt-image") and quality:
            kwargs["quality"] = quality
        result = self._retry(lambda: self.media_client.images.generate(**kwargs))
        item = result.data[0]
        if getattr(item, "b64_json", None):
            Path(out_path).write_bytes(base64.b64decode(item.b64_json))
        elif getattr(item, "url", None):
            import urllib.request

            urllib.request.urlretrieve(item.url, out_path)
        else:
            raise RuntimeError("Image API returned neither b64_json nor url")
        self.usage.record_image(self.m.image, seconds=time.time() - started, label=out_path)
        return out_path

    def tts(self, text: str, out_path: str, *, voice: str = "alloy") -> str:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        started = time.time()
        kwargs: dict[str, Any] = {
            "model": self.m.tts, "voice": voice, "input": text, "response_format": "mp3",
        }
        if self.m.tts.startswith("gpt-4o-mini-tts"):
            kwargs["instructions"] = (
                "Warm, clear teacher voice. Moderate pace, natural pauses at sentence "
                "ends, slight emphasis on key terms."
            )

        def call() -> None:
            with self.media_client.audio.speech.with_streaming_response.create(**kwargs) as resp:
                resp.stream_to_file(out_path)

        self._retry(call)
        self.usage.record_tts(self.m.tts, len(text), seconds=time.time() - started, label=out_path)
        return out_path

    # ------------------------------------------------------------------ internals
    def _json_loop(
        self,
        messages: list[dict[str, Any]],
        schema: Type[T],
        *,
        model: str,
        max_tokens: int,
        effort: str | None,
        label: str,
    ) -> T:
        last_err: Exception | None = None
        for _ in range(3):
            resp = self._create(
                model=model, messages=messages, max_tokens=max_tokens, effort=effort,
                label=label, response_format=self._response_format(schema),
            )
            raw = _strip_fences(_content(resp))
            try:
                return schema.model_validate_json(raw)
            except (ValidationError, json.JSONDecodeError) as e:
                last_err = e
                messages = [
                    *messages,
                    {"role": "assistant", "content": raw[:6000]},
                    {"role": "user", "content": f"Invalid JSON for the schema ({str(e)[:800]}). "
                                                "Return the corrected JSON object only."},
                ]
        raise RuntimeError(f"{label} failed after retries: {last_err}")

    def _response_format(self, schema: Type[BaseModel]) -> dict[str, Any]:
        if self._json_schema_supported:
            return {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
            }
        return {"type": "json_object"}

    def _create(
        self,
        *,
        model: str,
        messages: list,
        max_tokens: int,
        effort: str | None = None,
        label: str = "",
        **extra: Any,
    ):
        kwargs: dict[str, Any] = {"model": model, "messages": messages, **extra}
        reasoning = _is_reasoning_model(model)
        budget = max(max_tokens, self.m.max_completion_tokens) if reasoning else max_tokens
        level = (effort or self.m.reasoning_effort) if reasoning else None

        for escalation in range(3):
            if reasoning:
                kwargs["max_completion_tokens"] = budget
                if level:
                    kwargs["reasoning_effort"] = level
            else:
                kwargs["max_tokens"] = budget
            started = time.time()

            def call():
                try:
                    return self.client.chat.completions.create(**kwargs)
                except Exception as exc:  # parameter fallbacks, then re-raise
                    text = str(exc)
                    if "reasoning_effort" in text and "reasoning_effort" in kwargs:
                        kwargs.pop("reasoning_effort", None)
                        return self.client.chat.completions.create(**kwargs)
                    if (kwargs.get("response_format", {}).get("type") == "json_schema"
                            and any(t in text for t in ("json_schema", "response_format", "schema"))):
                        # Relays that enforce strict schemas reject pydantic's defaults; the
                        # schema is still in the system prompt, so json_object is enough.
                        self._json_schema_supported = False
                        kwargs["response_format"] = {"type": "json_object"}
                        return self.client.chat.completions.create(**kwargs)
                    if "max_completion_tokens" in text and "max_completion_tokens" in kwargs:
                        kwargs["max_tokens"] = kwargs.pop("max_completion_tokens")
                        return self.client.chat.completions.create(**kwargs)
                    raise

            resp = self._retry(call)
            usage = getattr(resp, "usage", None)
            if usage is not None:
                details = getattr(usage, "completion_tokens_details", None)
                self.usage.record_tokens(
                    "vision" if label.startswith("vision") else "chat",
                    model,
                    input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                    output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                    reasoning_tokens=int(getattr(details, "reasoning_tokens", 0) or 0) if details else 0,
                    seconds=time.time() - started,
                    label=label + (f"#budget{escalation}" if escalation else ""),
                )
            # Reasoning models can spend the whole budget thinking and return nothing.
            truncated = _finish_reason(resp) == "length" or not _content(resp).strip()
            if not truncated or budget >= 64000:
                return resp
            budget = min(64000, budget * 2)
            level = _lower_effort(level)
            print(f"    [provider] {label}: output truncated; retrying with {budget} tokens, effort={level}", flush=True)
        return resp

    @staticmethod
    def _retry(fn, attempts: int = 4):
        last_err: Exception | None = None
        for attempt in range(attempts):
            try:
                return fn()
            except Exception as exc:
                last_err = exc
                name = type(exc).__name__
                text = str(exc).lower()
                transient = (
                    any(token in name for token in _TRANSIENT)
                    or "disconnect" in text
                    or any(code in text for code in ("502", "503", "504"))
                )
                if not transient or attempt == attempts - 1:
                    raise
                time.sleep(2.0 * (attempt + 1))
        raise last_err  # pragma: no cover


_EFFORTS = ["minimal", "low", "medium", "high"]


def _lower_effort(level: str | None) -> str | None:
    if level not in _EFFORTS:
        return level
    return _EFFORTS[max(0, _EFFORTS.index(level) - 1)]


def _finish_reason(resp) -> str:
    try:
        return str(resp.choices[0].finish_reason or "")
    except Exception:
        return ""


def _is_reasoning_model(model: str) -> bool:
    return model.startswith(("gpt-5", "o1", "o3", "o4")) and "chat" not in model


def _json_system(system: str, schema: Type[BaseModel]) -> str:
    schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
    return (
        (system + "\n\n" if system else "")
        + "Respond with ONLY a JSON object matching this JSON Schema (no prose, no fences):\n"
        + schema_json
    )


def _image_content(prompt: str, image_paths: list[str], detail: str = "high") -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for p in image_paths:
        b64 = base64.b64encode(Path(p).read_bytes()).decode()
        mime = "image/png" if str(p).lower().endswith(".png") else "image/jpeg"
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}", "detail": detail}}
        )
    return content


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    return raw


def _content(resp) -> str:
    try:
        return resp.choices[0].message.content or ""
    except Exception:
        return ""
