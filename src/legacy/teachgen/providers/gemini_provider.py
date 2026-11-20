"""Optional Gemini backend — wraps the repo's existing gpt_request.py helpers.

This exists to prove the Provider seam: the rest of teachgen never changes when
you swap backends. Implemented as a thin adapter stub; fill in the bodies by
delegating to src/gpt_request.py (request_gemini_token, request_gemini_video_img_token)
and TeachingMonster's TTS if you want a non-OpenAI path.
"""

from __future__ import annotations

from typing import Type, TypeVar

from pydantic import BaseModel

from ..config import Config
from ..schema import WordTiming

T = TypeVar("T", bound=BaseModel)


class GeminiProvider:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def chat(self, prompt: str, *, system: str = "", max_tokens: int = 4000) -> str:
        raise NotImplementedError(
            "GeminiProvider.chat: delegate to src.gpt_request.request_gemini_token"
        )

    def chat_json(self, prompt, schema: Type[T], *, system="", max_tokens=4000) -> T:
        raise NotImplementedError("GeminiProvider.chat_json: wrap request_gemini_token + parse")

    def vision(self, prompt, images, *, system="", max_tokens=4000) -> str:
        raise NotImplementedError(
            "GeminiProvider.vision: wrap request_gemini_video_img_token (native video input)"
        )

    def tts(self, text, *, voice="alloy") -> tuple[bytes, list[WordTiming]]:
        raise NotImplementedError("GeminiProvider.tts: wrap TeachingMonster TTSModule")

    def image(self, prompt, *, size="1536x1024", quality="high") -> bytes:
        raise NotImplementedError("GeminiProvider.image: no native image gen; route to OpenAI")
