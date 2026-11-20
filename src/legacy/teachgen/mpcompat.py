"""moviepy 1.x / 2.x compatibility shim.

moviepy 2.0 dropped the `moviepy.editor` namespace and renamed the fluent setters
(set_duration -> with_duration, set_audio -> with_audio, resize -> resized, ...).
This module exposes the clip classes and a handful of version-agnostic helpers so the
rest of teachgen doesn't care which moviepy is installed.
"""

from __future__ import annotations

try:  # moviepy 2.x
    from moviepy import (
        AudioFileClip,
        CompositeAudioClip,
        CompositeVideoClip,
        ImageClip,
        VideoFileClip,
        concatenate_videoclips,
    )
except ImportError:  # moviepy 1.x
    from moviepy.editor import (  # type: ignore
        AudioFileClip,
        CompositeAudioClip,
        CompositeVideoClip,
        ImageClip,
        VideoFileClip,
        concatenate_videoclips,
    )

__all__ = [
    "AudioFileClip",
    "CompositeAudioClip",
    "CompositeVideoClip",
    "ImageClip",
    "VideoFileClip",
    "concatenate_videoclips",
    "with_duration",
    "with_audio",
    "resized",
    "subclipped",
]


def with_duration(clip, d):
    fn = getattr(clip, "with_duration", None) or clip.set_duration
    return fn(d)


def with_audio(clip, audio):
    fn = getattr(clip, "with_audio", None) or clip.set_audio
    return fn(audio)


def resized(clip, size):
    fn = getattr(clip, "resized", None) or clip.resize
    return fn(size)


def subclipped(clip, start, end):
    fn = getattr(clip, "subclipped", None) or clip.subclip
    return fn(start, end)
