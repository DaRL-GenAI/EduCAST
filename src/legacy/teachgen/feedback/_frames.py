"""Shared video-frame sampling used by both reviewer and outer_reviewer."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path


def sample_frames(video_path: Path, n: int) -> list[bytes]:
    """Return n evenly-spaced frames from *video_path* as PNG bytes."""
    from ..mpcompat import VideoFileClip
    from PIL import Image

    clip = VideoFileClip(str(video_path))
    try:
        dur = clip.duration
        out: list[bytes] = []
        for i in range(n):
            t = dur * (i + 0.5) / n
            frame = clip.get_frame(t)
            buf = BytesIO()
            Image.fromarray(frame).save(buf, format="PNG")
            out.append(buf.getvalue())
        return out
    finally:
        clip.close()
