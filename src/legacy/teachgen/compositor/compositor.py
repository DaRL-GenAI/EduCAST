"""Assemble per-segment visuals + narration into the final video.

Handles both visual kinds uniformly:
  - image  -> ImageClip stretched to the narration duration (slide / concept image)
  - video  -> animation clip; if shorter than narration we freeze the last frame to
              fill, if longer we let it run and pad the audio with trailing silence.

This is the same moviepy compositing approach TeachingMonster uses, generalized to a
mixed list of static and dynamic segments. Cursor overlays (from code2video / TM) can
be layered in per-segment here later using NarrationAudio.words.
"""

from __future__ import annotations

from pathlib import Path

from ..mpcompat import (
    AudioFileClip,
    CompositeAudioClip,
    ImageClip,
    VideoFileClip,
    concatenate_videoclips,
    resized,
    subclipped,
    with_audio,
    with_duration,
)
from ..schema import NarrationAudio, VisualAsset


def assemble(
    visuals: list[VisualAsset],
    audios: list[NarrationAudio],
    out_path: Path,
    *,
    fps: int = 24,
    size: tuple[int, int] = (1920, 1080),
) -> Path:
    audio_by_seg = {a.segment_id: a for a in audios}
    clips = []

    for v in visuals:
        narr = audio_by_seg[v.segment_id]
        audio = AudioFileClip(narr.path)
        dur = max(narr.duration, audio.duration)

        if v.kind == "image":
            visual = resized(with_duration(ImageClip(v.path), dur), size)
            visual = with_audio(visual, audio)
        else:  # video (animation)
            visual = resized(VideoFileClip(v.path), size)
            if visual.duration < dur:
                visual = _freeze_to(visual, dur)
            audio = _fit_audio(audio, visual.duration)
            visual = with_audio(visual, audio)

        clips.append(visual)

    final = concatenate_videoclips(clips, method="compose")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    final.write_videofile(
        str(out_path),
        fps=fps,
        codec="libx264",
        audio_codec="aac",
        audio_bitrate="192k",
        # yuv420p + faststart => plays in browsers, QuickTime, and most embedded previews.
        ffmpeg_params=["-pix_fmt", "yuv420p", "-movflags", "+faststart"],
        logger=None,
    )
    final.close()
    for c in clips:
        c.close()
    return out_path


def _freeze_to(clip, target: float):
    """Extend a short animation by holding its last frame to `target` seconds."""
    try:
        from moviepy.video.fx import freeze as _freeze  # moviepy 2.x

        return clip.with_effects([_freeze.Freeze(t="end", total_duration=target)])
    except Exception:
        try:
            from moviepy.video.fx.freeze import freeze  # moviepy 1.x

            return freeze(clip, t="end", total_duration=target)
        except Exception:
            return with_duration(clip, target)  # last resort: let moviepy clamp/loop


def _fit_audio(audio, target: float):
    """Pad narration with trailing silence so it spans the (longer) animation."""
    if audio.duration >= target:
        return subclipped(audio, 0, target)
    return with_duration(CompositeAudioClip([audio]), target)
