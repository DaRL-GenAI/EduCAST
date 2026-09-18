"""Narration (TTS) preparation — API side of Stage 2.

Audio is synthesized once per (text, voice, model) and cached in the scene's
work dir so repair rounds never pay for narration twice.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..config import Config
from ..providers.base import Provider
from ..schema import PreparedScene, SceneBrief
from .media import probe_duration


def narration_key(cfg: Config, text: str) -> str:
    raw = f"{cfg.models.tts}|{cfg.voice}|{cfg.request.language}|{text.strip()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def prepare_narration(
    cfg: Config,
    provider: Provider,
    scene: SceneBrief,
    work: Path,
    prior: PreparedScene | None,
) -> tuple[str | None, float | None, str]:
    """Return (relative mp3 path, seconds, cache key). Reuses prior audio when text is unchanged."""
    text = (scene.narration or "").strip()
    if not cfg.enable_narration or not text:
        return None, None, ""
    key = narration_key(cfg, text)
    if (
        prior is not None
        and prior.narration_path
        and prior.debug.get("narration_key") == key
        and (cfg.run_dir / prior.narration_path).is_file()
    ):
        return prior.narration_path, prior.narration_seconds, key
    out = work / "narration.mp3"
    provider.tts(text, str(out), voice=cfg.voice)
    seconds = probe_duration(out)
    return str(out.relative_to(cfg.run_dir)), seconds, key
