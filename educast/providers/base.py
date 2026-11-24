"""Provider protocol."""

from __future__ import annotations

from typing import Protocol, Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class Provider(Protocol):
    """One API key behind one interface; every stage talks only to this.

    `effort` is a hint for reasoning models (minimal | low | medium | high) and
    may be ignored by backends that do not support it.
    """

    def chat(
        self,
        prompt: str,
        *,
        system: str = "",
        max_tokens: int = 4000,
        model: str | None = None,
        effort: str | None = None,
    ) -> str: ...

    def chat_json(
        self,
        prompt: str,
        schema: Type[T],
        *,
        system: str = "",
        max_tokens: int = 4000,
        model: str | None = None,
        effort: str | None = None,
    ) -> T: ...

    def vision(
        self,
        prompt: str,
        image_paths: list[str],
        *,
        system: str = "",
        max_tokens: int = 2000,
        effort: str | None = None,
    ) -> str: ...

    def vision_json(
        self,
        prompt: str,
        image_paths: list[str],
        schema: Type[T],
        *,
        system: str = "",
        max_tokens: int = 2000,
        effort: str | None = None,
    ) -> T: ...

    def image(self, prompt: str, out_path: str, *, size: str = "1536x1024") -> str: ...

    def tts(self, text: str, out_path: str, *, voice: str = "alloy") -> str: ...
