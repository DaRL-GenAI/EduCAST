"""The Provider Protocol that every backend must satisfy."""

from __future__ import annotations

from typing import Protocol, Type, TypeVar, runtime_checkable

from pydantic import BaseModel

from ..schema import WordTiming

T = TypeVar("T", bound=BaseModel)


@runtime_checkable
class Provider(Protocol):
    """All generative capabilities the pipeline needs, behind one interface."""

    def chat(self, prompt: str, *, system: str = "", max_tokens: int = 4000) -> str:
        """Plain text in, plain text out."""
        ...

    def chat_json(
        self, prompt: str, schema: Type[T], *, system: str = "", max_tokens: int = 4000
    ) -> T:
        """Structured output validated against a pydantic model (with retry)."""
        ...

    def vision(
        self, prompt: str, images: list[bytes], *, system: str = "", max_tokens: int = 4000
    ) -> str:
        """Multimodal: prompt + a list of image bytes (e.g. sampled video frames)."""
        ...

    def tts(self, text: str, *, voice: str = "alloy") -> tuple[bytes, list[WordTiming]]:
        """Narration text -> (audio bytes, word-level timings for A/V alignment)."""
        ...

    def image(self, prompt: str, *, size: str = "1536x1024", quality: str = "high") -> bytes:
        """Text-to-image -> PNG bytes."""
        ...
