"""Provider abstraction — the 'one key' layer.

Every model call (text, structured, vision, TTS, image) goes through a Provider.
The default OpenAIProvider routes everything to OpenAI so a single OPENAI_API_KEY
is all the user needs. Alternate backends (e.g. Gemini) implement the same
Protocol and are otherwise invisible to the rest of the system.
"""

from __future__ import annotations

from ..config import Config
from .base import Provider


def get_provider(cfg: Config) -> Provider:
    if cfg.provider == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(cfg)
    if cfg.provider == "gemini":
        from .gemini_provider import GeminiProvider

        return GeminiProvider(cfg)
    raise ValueError(f"unknown provider: {cfg.provider!r}")


__all__ = ["Provider", "get_provider"]
