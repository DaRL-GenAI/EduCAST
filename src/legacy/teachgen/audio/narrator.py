"""Segment narration -> audio file + word timings.

Narration-driven alignment: the TTS duration defines each segment's length. The
compositor stretches static visuals to fit, and the animation renderer is asked to
aim for the same target. Word timings are carried through for any cursor/keyword sync.
"""

from __future__ import annotations

from pathlib import Path

from ..providers.base import Provider
from ..schema import NarrationAudio, Segment


def narrate(provider: Provider, seg: Segment, out_dir: Path, *, voice: str = "alloy") -> NarrationAudio:
    audio_bytes, words = provider.tts(seg.narration, voice=voice)

    path = out_dir / f"{seg.id}.mp3"
    path.write_bytes(audio_bytes)

    duration = _audio_duration(path, words)
    return NarrationAudio(segment_id=seg.id, path=str(path), duration=duration, words=words)


def _audio_duration(path: Path, words) -> float:
    """Prefer the last word's end time; fall back to probing the file."""
    if words:
        return float(words[-1].end)
    try:
        from ..mpcompat import AudioFileClip

        clip = AudioFileClip(str(path))
        d = float(clip.duration)
        clip.close()
        return d
    except Exception:
        return 0.0
