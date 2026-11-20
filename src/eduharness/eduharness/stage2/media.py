"""ffmpeg/ffprobe helpers shared by rendering, narration and review."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageStat

from ..schema import GuardFinding


_TOOL_CACHE: dict[str, str | None] = {}


def _resolve_tool(name: str) -> str | None:
    """First working `name` binary: $EDUHARNESS_<NAME>, then every PATH candidate.

    Some hosts ship a custom ffmpeg whose shared libraries are missing; a binary
    that cannot even print `-version` is skipped in favour of the next one.
    """
    if name in _TOOL_CACHE:
        return _TOOL_CACHE[name]
    candidates: list[str] = []
    override = os.environ.get(f"EDUHARNESS_{name.upper()}", "").strip()
    if override:
        candidates.append(override)
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(folder) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            candidates.append(str(candidate))
    for extra in ("/usr/bin", "/usr/local/bin", "/opt/homebrew/bin"):
        candidate = Path(extra) / name
        if candidate.is_file():
            candidates.append(str(candidate))
    # setup_env.sh installs wrappers here; renderers can be started without
    # sourcing env.sh (for example from the Studio or a notebook kernel).
    here = Path(__file__).resolve()
    stores = [here.parents[1]]
    configured_store = os.environ.get("EDUHARNESS_STORE", "").strip()
    if configured_store:
        stores.insert(0, Path(configured_store))
    if len(here.parents) > 4:
        stores.append(here.parents[4] / "eduharness" / "eduharness")
    for store in stores:
        candidate = store / "bin" / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            candidates.append(str(candidate))
    for candidate in candidates:
        try:
            ok = subprocess.run([candidate, "-version"], capture_output=True, timeout=20).returncode == 0
        except Exception:
            ok = False
        if ok:
            _TOOL_CACHE[name] = candidate
            return candidate
    _TOOL_CACHE[name] = None
    return None


def ffmpeg_bin() -> str:
    return _resolve_tool("ffmpeg") or "ffmpeg"


def ffprobe_bin() -> str:
    return _resolve_tool("ffprobe") or "ffprobe"


def ffmpeg_available() -> bool:
    return bool(_resolve_tool("ffmpeg") and _resolve_tool("ffprobe"))


def probe_duration(path: Path) -> float | None:
    try:
        value = subprocess.check_output(
            [
                ffprobe_bin(), "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(path),
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return float(value)
    except Exception:
        return None


@dataclass
class Frame:
    path: Path
    seconds: float
    label: str = "uniform"


def extract_video_frames(
    video_path: Path,
    out_dir: Path,
    stem: str,
    *,
    count: int = 5,
    extra_seconds: list[float] | None = None,
    max_width: int = 1280,
) -> list[Frame]:
    """Uniformly sample `count` frames plus any guard-flagged timestamps."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob(f"{stem}_f*.jpg"):
        old.unlink(missing_ok=True)
    duration = probe_duration(video_path) or 3.0
    count = max(1, count)
    if count == 1:
        stamps = [(0.5 * duration, "uniform")]
    else:
        stamps = [
            (min(duration - 0.05, max(0.0, duration * (0.06 + 0.88 * i / (count - 1)))), "uniform")
            for i in range(count)
        ]
    for t in extra_seconds or []:
        t = min(max(0.0, float(t)), max(0.0, duration - 0.05))
        if all(abs(t - s) > 0.35 for s, _ in stamps):
            stamps.append((t, "guard"))
    stamps.sort(key=lambda item: item[0])
    frames: list[Frame] = []
    for i, (t, label) in enumerate(stamps):
        out = out_dir / f"{stem}_f{i}.jpg"
        subprocess.run(
            [
                ffmpeg_bin(), "-y", "-ss", f"{t:.3f}", "-i", str(video_path),
                "-frames:v", "1", "-q:v", "3", "-vf", f"scale='min({max_width},iw)':-2",
                str(out),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if out.is_file():
            frames.append(Frame(path=out, seconds=round(t, 3), label=label))
    return frames


def blank_frame_findings(frames: list[Frame], *, threshold: float = 3.0) -> list[GuardFinding]:
    """Flag frames that are (nearly) a flat color — a sign of a broken render."""
    blank: list[Frame] = []
    for frame in frames:
        try:
            with Image.open(frame.path) as img:
                stat = ImageStat.Stat(img.convert("L"))
                if stat.stddev[0] < threshold:
                    blank.append(frame)
        except Exception:
            continue
    if not blank:
        return []
    if len(blank) == len(frames):
        return [GuardFinding(kind="blank_frame", severity="blocker",
                             message="every sampled frame is a flat color (nothing rendered)")]
    return [
        GuardFinding(kind="blank_frame", severity="major",
                     message=f"frame at {f.seconds:.1f}s is a flat color", at_seconds=f.seconds)
        for f in blank
        if f.seconds > 0.5  # a blank opening frame is normal
    ]


def mux_narration(
    video: Path,
    audio: Path,
    out: Path,
    *,
    tail_seconds: float = 0.6,
) -> float:
    """Combine a silent visual with a narration track.

    The longer of the two decides the length: video is held on its last frame
    while narration finishes; narration is padded with silence while the
    animation finishes. Returns the resulting duration.
    """
    vdur = probe_duration(video) or 0.0
    adur = probe_duration(audio) or 0.0
    total = max(vdur, adur) + tail_seconds
    vpad = max(0.0, total - vdur)
    apad = max(0.0, total - adur)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".mux.mp4")
    cmd = [
        ffmpeg_bin(), "-y", "-i", str(video), "-i", str(audio),
        "-filter_complex",
        f"[0:v]tpad=stop_mode=clone:stop_duration={vpad:.3f},format=yuv420p[v];"
        f"[1:a]apad=pad_dur={apad:.3f}[a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        "-t", f"{total:.3f}", str(tmp),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    tmp.replace(out)
    return probe_duration(out) or total


def ensure_web_playable(video: Path) -> None:
    """Re-encode in place to H.264/yuv420p + faststart when the codec is not browser friendly."""
    try:
        codec = subprocess.check_output(
            [
                ffprobe_bin(), "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=codec_name,pix_fmt", "-of", "csv=p=0", str(video),
            ],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return
    if codec.startswith("h264") and "yuv420p" in codec:
        return
    tmp = video.with_suffix(".web.mp4")
    subprocess.run(
        [
            ffmpeg_bin(), "-y", "-i", str(video), "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(tmp),
        ],
        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if tmp.is_file() and tmp.stat().st_size > 0:
        tmp.replace(video)
