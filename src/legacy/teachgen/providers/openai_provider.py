"""Default backend: everything via OpenAI, driven by a single OPENAI_API_KEY."""

from __future__ import annotations

import base64
import io
import json
import tempfile
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

from ..config import Config
from ..schema import WordTiming

T = TypeVar("T", bound=BaseModel)


class OpenAIProvider:
    def __init__(self, cfg: Config):
        try:
            from openai import OpenAI
        except ImportError as e:  # pragma: no cover
            raise SystemExit("Missing dependency. Run: pip install openai") from e
        self.cfg = cfg
        self.m = cfg.models
        self.client = OpenAI(api_key=cfg.api_key)

    # ------------------------------------------------------------------ text
    def chat(self, prompt: str, *, system: str = "", max_tokens: int = 4000) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = self.client.chat.completions.create(
            model=self.m.text, messages=messages, max_tokens=max_tokens
        )
        return resp.choices[0].message.content.strip()

    def chat_json(
        self, prompt: str, schema: Type[T], *, system: str = "", max_tokens: int = 4000
    ) -> T:
        """JSON mode + pydantic validation, with one self-correcting retry."""
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        sys_msg = (
            (system + "\n\n" if system else "")
            + "Respond with ONLY a JSON object matching this JSON Schema:\n"
            + schema_json
        )
        messages = [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": prompt},
        ]
        last_err = None
        for attempt in range(2):
            resp = self.client.chat.completions.create(
                model=self.m.text,
                messages=messages,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content
            try:
                return schema.model_validate_json(raw)
            except (ValidationError, ValueError) as e:
                last_err = e
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {"role": "user", "content": f"That failed validation: {e}. Fix and resend."}
                )
        raise ValueError(f"chat_json failed schema validation: {last_err}")

    # ---------------------------------------------------------------- vision
    def vision(
        self, prompt: str, images: list[bytes], *, system: str = "", max_tokens: int = 4000
    ) -> str:
        content = [{"type": "text", "text": prompt}]
        for img in images:
            b64 = base64.b64encode(img).decode()
            content.append(
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
            )
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})
        resp = self.client.chat.completions.create(
            model=self.m.vision, messages=messages, max_tokens=max_tokens
        )
        return resp.choices[0].message.content.strip()

    # ------------------------------------------------------------------- tts
    def tts(self, text: str, *, voice: str = "alloy") -> tuple[bytes, list[WordTiming]]:
        """Synthesize speech, then transcribe it back for word-level timings.

        OpenAI's TTS endpoint does not return timestamps, so we run the audio
        through whisper with word granularity. This double pass is what lets the
        compositor sync visuals (and any cursor) to the spoken words.
        """
        speech = self.client.audio.speech.create(
            model=self.m.tts, voice=voice, input=text
        )
        audio_bytes = speech.read() if hasattr(speech, "read") else speech.content

        words: list[WordTiming] = []
        with tempfile.NamedTemporaryFile(suffix=".mp3") as tmp:
            tmp.write(audio_bytes)
            tmp.flush()
            with open(tmp.name, "rb") as fh:
                tr = self.client.audio.transcriptions.create(
                    model=self.m.transcribe,
                    file=fh,
                    response_format="verbose_json",
                    timestamp_granularities=["word"],
                )
            for w in getattr(tr, "words", None) or []:
                words.append(
                    WordTiming(
                        word=getattr(w, "word", ""),
                        start=getattr(w, "start", 0.0),
                        end=getattr(w, "end", 0.0),
                    )
                )
        return audio_bytes, words

    # ----------------------------------------------------------------- image
    def image(self, prompt: str, *, size: str = "1536x1024", quality: str = "high") -> bytes:
        result = self.client.images.generate(
            model=self.m.image, prompt=prompt, size=size, quality=quality, n=1
        )
        b64 = result.data[0].b64_json
        if b64:
            return base64.b64decode(b64)
        # Some deployments return a URL instead of inline base64.
        import urllib.request

        with urllib.request.urlopen(result.data[0].url) as r:
            return r.read()
