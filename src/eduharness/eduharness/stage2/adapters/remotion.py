"""Remotion tool adapter.

The Executor picks one of a few hardened motion-graphics *beats* and fills its
text fields; the pinned remotion_template renders it in-place from --props.
Falls back to a Pillow + ffmpeg slide only if Remotion/Node/Chrome are missing.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from PIL import Image, ImageDraw

from ... import presentation
from ...providers.base import Provider
from ...schema import SceneBrief, StyleConfig, layout_contract, scene_layout_text, teaching_board
from ..media import ffmpeg_bin
from .fonts import load_font

SYSTEM = """\
You design one motion-graphics beat for a teaching video using a fixed set of
hardened layouts. You only fill text fields; you never write code.

Beats. Each one draws ONLY the fields listed for it. A field you fill that its
beat does not draw is silently discarded, so a key element that depends on it can
never be satisfied -- pick the beat that draws what the brief requires.
- title_card: subtitle, accent_label. Use for openers.
- bullets: bullets (2-5). The default teaching block.
- formula: formula, large and dominant, with bullets listed beneath it. Use when
  one equation is the anchor and the rest is supporting detail.
- compare: left_title + left_items and right_title + right_items (max 3 each),
  and formula as a rule strip under the two columns. Use for contrasts, for
  misconception vs correction, and whenever two labelled lists are the point.
- steps: steps (2-5), numbered. Use for procedures / worked examples.
- recap: bullets and formula, drawn together as one closing block. It does NOT
  split into columns: left_items / right_items are ignored here.
- stat_row: stats (2-4 tiles), each {value, unit, name}. Use when the point is a
  handful of numbers the student should hold on to.

`highlights` (max 4) lists exact substrings of the text that beat draws; each match
is rendered in the secondary colour and bolder. Use it when the brief asks for a
term or an equation to be emphasised. It applies to `formula` (formula beat and the
compare strip) and to the bullets/recap block; `title_card` ignores it.
`subtitle` is drawn by `title_card` only.

`title_card` is the lesson opener and the ONE beat that is not a teaching board:
it owns a hard-coded stage (cast leaning in from the bottom corners, title and
subtitle surfacing in the middle), so give it only a title, a short subtitle and
an optional accent label — never bullets, formulas or stats.

Every other scene should feel like an authored teaching board: choose a deliberate
visual hierarchy and include a concrete takeaway. The right visual region is
reserved for the scene's actual visual content; do not add a character panel.

Rules: every string is plain text (no markdown, no LaTeX, no color codes); bullets/steps
<= 70 characters; titles <= 48 characters. Match the narration's pacing and content.
Apart from `title_card`, the composition must use the shared teaching-board layout:
fixed title band, left explanation column, right visual column, and a normalized
6x6 A1-F6 anchor grid. Do not place content in the footer band or let labels overlap.
"""

REMOTION_VERSION = "4.0.200"
Beat = Literal["title_card", "bullets", "formula", "compare", "steps", "recap", "stat_row"]


def _list_cap(model: type[BaseModel], field_name: str | None, default: int = 5) -> int:
    """The max_length declared on a list field, so validators cannot drift from it."""
    field = model.model_fields.get(field_name or "")
    for constraint in getattr(field, "metadata", ()) or ():
        limit = getattr(constraint, "max_length", None)
        if isinstance(limit, int):
            return limit
    return default


class RemotionSpec(BaseModel):
    beat: Beat = "bullets"
    title: str = "Teaching Scene"
    subtitle: str = ""
    bullets: list[str] = Field(default_factory=list, max_length=5)
    formula: str = ""
    highlights: list[str] = Field(default_factory=list, max_length=4)
    left_title: str = ""
    left_items: list[str] = Field(default_factory=list, max_length=3)
    right_title: str = ""
    right_items: list[str] = Field(default_factory=list, max_length=3)
    steps: list[str] = Field(default_factory=list, max_length=5)
    stats: list[dict] = Field(default_factory=list, max_length=4)
    accent_label: str = ""
    character: int = Field(default=1, ge=1, le=6)
    motion: str = "fade-up"

    @field_validator("bullets", "steps", "left_items", "right_items", "highlights", mode="before")
    @classmethod
    def clean_list(cls, value, info):
        """Clip each list to *its own* cap, not to a shared one.

        These fields have different limits (bullets/steps 5, highlights 4,
        left_items/right_items 3). Trimming every one of them to 5 meant a model
        that returned 4 right_items produced a hard validation error instead of a
        clipped list -- the scene then failed preparation and never rendered at
        all, which is far worse than dropping one line. The cap is read from the
        field itself so the two can never drift apart again.
        """
        if not value:
            return []
        return [str(x).strip()[:90] for x in value if str(x).strip()][: _list_cap(cls, info.field_name)]

    @field_validator("title", "subtitle", "formula", "left_title", "right_title", "accent_label", mode="before")
    @classmethod
    def clean_text(cls, value):
        return str(value or "").strip()[:120]


# Backward-compatible alias used by older checkpoints/tests.
_RemotionSpec = RemotionSpec


TITLE_CARD_ONLY_FIELDS = ("bullets", "formula", "highlights", "left_title", "left_items",
                          "right_title", "right_items", "steps", "stats")


def as_title_card(spec: RemotionSpec) -> RemotionSpec:
    """Force the opener onto its own stage, whatever beat the model reached for.

    The opener is a hard contract, not a suggestion: a board beat here would put a
    lecture column and a result strip on the title screen. Board-only fields are
    cleared so nothing from a rejected beat leaks into the props.
    """
    data = spec.model_dump()
    data["beat"] = "title_card"
    for field in TITLE_CARD_ONLY_FIELDS:
        data[field] = [] if isinstance(data.get(field), list) else ""
    return RemotionSpec.model_validate(data)


def generate_spec(
    provider: Provider,
    brief: SceneBrief,
    feedback: str = "",
    *,
    style: StyleConfig | None = None,
    prior_spec: dict | None = None,
    repair_ops: list | None = None,
    narration_seconds: float | None = None,
    opener: bool = False,
) -> RemotionSpec:
    style = style or StyleConfig()
    seconds = narration_seconds or brief.target_seconds or 8
    elements = "\n".join(f"  - {e}" for e in brief.key_elements) or "  (none listed)"
    prompt = f"""\
TITLE HINT: {brief.title}
NARRATION ({seconds:.0f}s): {brief.narration}
VISUAL BRIEF: {brief.visual_brief}
{layout_contract(style)}
PLANNED ELEMENT PLACEMENTS:
{scene_layout_text(brief)}
KEY ELEMENTS THAT MUST APPEAR AS TEXT ON SCREEN:
{elements}

Choose the best beat for this brief and fill only its fields.
"""
    if opener:
        prompt += (
            "\nTHIS SCENE IS THE LESSON OPENER: the beat is `title_card` and nothing else.\n"
            "Fill `title` (the lesson name), `subtitle` (one short line, <= 60 characters)\n"
            "and optionally `accent_label`. Leave bullets, formula, steps and stats empty —\n"
            "the opener has no lecture column and no result strip to put them in.\n"
        )
    if prior_spec:
        prompt += (
            "\nPRIOR SPEC (this version FAILED review; keep what worked, fix what the feedback "
            "names, and switch to a different beat if the current layout cannot show the key "
            "elements — e.g. bullets + a formula card need `recap`):\n"
            + json.dumps(prior_spec, ensure_ascii=False, indent=2)
            + "\n"
        )
    if repair_ops:
        prompt += "\nSTRUCTURED REPAIR OPS (apply these precisely):\n"
        for op in repair_ops:
            dump = op.model_dump() if hasattr(op, "model_dump") else op
            prompt += f"- {dump}\n"
    if feedback:
        prompt += f"\nFIX FEEDBACK:\n{feedback}\n"
    spec = provider.chat_json(prompt, RemotionSpec, system=SYSTEM, max_tokens=2000)
    return as_title_card(spec) if opener else spec


def template_root() -> Path:
    return Path(__file__).resolve().parents[3] / "remotion_template"


def chrome_is_complete(binary: Path) -> bool:
    """Whether a Chrome build ships the resource files it needs to launch.

    Every Chrome for Testing / Playwright bundle keeps ``icudtl.dat`` next to
    the executable.  A binary unzipped on its own still answers ``--version``,
    so a smoke test cannot tell the two apart — but it dies at launch with
    "Invalid file descriptor to ICU data received", which Remotion reports only
    as a browser-launch failure and the pipeline turns into a static slide.
    Checking for the ICU table is what separates a usable build from a torso.
    """
    return (binary.parent / "icudtl.dat").is_file()


def _browser_candidates(template: Path) -> list[Path]:
    """Chrome builds to try, best source first (Remotion's own, Playwright, bundled)."""
    candidates: list[Path] = []
    own = template / "node_modules" / ".remotion" / "chrome-headless-shell"
    candidates.extend(
        sorted(
            candidate
            for candidate in own.rglob("chrome-headless-shell*")
            if candidate.is_file() and os.access(candidate, os.X_OK) and candidate.suffix == ""
        )
    )
    cache = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", Path.home() / ".cache" / "ms-playwright"))
    for pattern in ("chromium_headless_shell-*/chrome-*/chrome-headless-shell",
                    "chromium_headless_shell-*/chrome-*/headless_shell",
                    "chromium-*/chrome-*/chrome"):
        matches = sorted(cache.glob(pattern))
        if matches:
            candidates.append(matches[-1])
    # Keep the bundled headless shell under the project tree.  This is used on
    # hosts where Playwright's cache is absent (or points at /root), and its
    # companion libraries are loaded by ``_browser_env`` below.
    for root in (template.parent / "eduharness", template.parents[2] / "eduharness" / "eduharness"):
        bundled = root / "runtime" / "chrome-headless-shell-linux64" / "chrome-headless-shell"
        if bundled.is_file() and os.access(bundled, os.X_OK):
            candidates.append(bundled)
    return candidates


def browser_executable(template: Path) -> str | None:
    """Chrome binary for Remotion: env override, Remotion's own download, or Playwright's shell.

    A later source that is complete beats an earlier one that is not: a partial
    download in ``node_modules/.remotion`` used to shadow a working bundle and
    send every Remotion scene down the static-slide fallback.
    """
    override = os.environ.get("EDUHARNESS_BROWSER_EXECUTABLE", "").strip()
    if override and Path(override).is_file():
        return override
    candidates = _browser_candidates(template)
    for candidate in candidates:
        if chrome_is_complete(candidate):
            return str(candidate)
    # Nothing looks complete: hand back the first candidate anyway so the
    # failure stays where it was rather than becoming "no browser at all".
    return str(candidates[0]) if candidates else None


def _browser_env(template: Path) -> dict[str, str]:
    """Environment for Chromium, including project-local NSS/NSPR libraries.

    The downloaded headless shell depends on libnss3/libnspr4, which may not be
    installed system-wide in the execution image.  Those debs are extracted
    below ``eduharness/browser-libs`` so rendering never writes to /usr or
    relies on /root caches.
    """
    env = {**os.environ, "npm_config_prefix": str(template), "CI": "1"}
    for root in (template.parent / "eduharness", template.parents[2] / "eduharness" / "eduharness"):
        libs = root / "browser-libs" / "usr" / "lib" / "x86_64-linux-gnu"
        if libs.is_dir():
            prior = env.get("LD_LIBRARY_PATH", "")
            env["LD_LIBRARY_PATH"] = f"{libs}:{prior}" if prior else str(libs)
            break
    return env


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _acquire_lock(lock: Path, what: str, attempts: int) -> None:
    """Take an exclusive file lock, reclaiming one whose owner is gone.

    These locks only serialize renders; they are not a record of failure.  A
    render killed mid-flight (OOM, Ctrl-C, a reaped job) used to leave the file
    behind forever, and every later scene then waited out the full timeout and
    silently downgraded to a static slide -- "Remotion is broken" when in fact
    nothing held the lock.  So a lock whose recorded pid is dead is stolen
    rather than waited on.
    """
    for _ in range(attempts):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return
        except FileExistsError:
            try:
                owner = int(lock.read_text(encoding="utf-8").strip() or 0)
            except (OSError, ValueError):
                owner = 0
            # 0 means an older build that wrote nothing, or a torn write; only
            # a pid we can prove is dead justifies stealing the lock.
            if owner and not _pid_alive(owner):
                lock.unlink(missing_ok=True)
                continue
            time.sleep(1)
    raise RuntimeError(f"Timed out waiting for Remotion {what} lock")


def ensure_remotion_deps(template: Path) -> None:
    """Install pinned deps once into remotion_template (not the repo root)."""
    marker = template / "node_modules" / "remotion" / "package.json"
    lock = template / ".eduharness_npm.lock"
    if marker.is_file():
        return
    _acquire_lock(lock, "npm install", 60)
    try:
        if marker.is_file():
            return
        subprocess.check_call(
            ["npm", "install", "--no-fund", "--no-audit"], cwd=str(template), timeout=900
        )
        if browser_executable(template) is None:
            subprocess.check_call(["npx", "remotion", "browser", "ensure"], cwd=str(template), timeout=600)
    finally:
        lock.unlink(missing_ok=True)


def render_with_remotion(
    template: Path,
    work_dir: Path,
    brief: SceneBrief,
    style: StyleConfig,
    spec: RemotionSpec,
    out_mp4: Path,
    duration: float,
    *,
    scene_index: int = 0,
    scene_total: int = 0,
) -> Path:
    ensure_remotion_deps(template)
    props = {
        **spec.model_dump(),
        "style": style.model_dump(),
        "durationInSeconds": float(max(2.0, duration)),
        "sceneLabel": brief.title,
        "sceneIndex": scene_index,
        "sceneTotal": scene_total,
        "character": ((max(1, scene_index) - 1) % 3) + 1,
        # All renderers consume the same board geometry.  Keep the brief's
        # lecture/result content alongside the board so old templates can still
        # render when a board is not present in hand-authored props.
        "board": teaching_board(style, brief),
        "lecture_lines": list(brief.lecture_lines),
        "takeaway": brief.takeaway,
        "visual_area": brief.visual_area,
        "result_area": brief.result_area,
    }
    props_path = work_dir / f"{brief.id}_props.json"
    props_path.write_text(json.dumps(props, ensure_ascii=False, indent=2), encoding="utf-8")
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    if out_mp4.exists():
        out_mp4.unlink()

    # Serialize Remotion renders — Chromium pools conflict across concurrent scenes.
    render_lock = template / ".eduharness_render.lock"
    _acquire_lock(render_lock, "render", 1800)

    log_path = work_dir / f"{brief.id}_remotion.log"
    try:
        cmd = [
            "npx", "remotion", "render", "src/index.ts", "SceneBeat", str(out_mp4.resolve()),
            f"--props={props_path.resolve()}", "--codec=h264", "--concurrency=2", "--log=info",
        ]
        chrome = browser_executable(template)
        if chrome:
            cmd.append(f"--browser-executable={chrome}")
        proc = subprocess.run(
            cmd, cwd=str(template), capture_output=True, text=True, timeout=900,
            env=_browser_env(template),
        )
        log_path.write_text(
            f"cmd={' '.join(cmd)}\nexit={proc.returncode}\n\nSTDOUT:\n{proc.stdout}\n\nSTDERR:\n{proc.stderr}\n",
            encoding="utf-8",
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Remotion render failed (exit {proc.returncode}). See {log_path}")
        if not out_mp4.is_file() or out_mp4.stat().st_size < 1000:
            raise RuntimeError(f"Remotion produced no usable mp4 at {out_mp4}")
        return out_mp4
    finally:
        render_lock.unlink(missing_ok=True)


# Backward-compatible private aliases
_render_with_remotion = render_with_remotion


def _paste_title_cast(canvas) -> None:
    """Lean the opener's cast in from the two bottom corners (Pillow twin of TitleCast).

    Same ratios as remotion_template/src/SceneBeat.tsx: each corner holds a pair
    that overlaps at the shoulder, the bodies run off the bottom edge so only head
    and torso show, and the outermost one is clipped by the side.
    """
    from PIL import Image

    width, height = canvas.size
    art_h = round(height * presentation.TITLE_CAST_HEIGHT_RATIO)
    art_w = round(art_h * presentation.TITLE_CAST_ASPECT)
    step = round(art_w * (1 - presentation.TITLE_CAST_HUG))
    top = height - art_h + round(height * presentation.TITLE_CAST_SUBMERGE)
    bite = round(art_w * presentation.TITLE_CAST_CORNER_BITE)
    for side, numbers in presentation.title_cast().items():
        for index, number in enumerate(numbers):
            source = presentation.character_asset(number)
            if not source.is_file():
                continue
            with Image.open(source) as raw:
                art = raw.convert("RGBA")
                scale = min(art_w / art.width, art_h / art.height)
                art = art.resize((max(1, round(art.width * scale)), max(1, round(art.height * scale))),
                                 Image.Resampling.LANCZOS)
            offset = index * step - bite
            left = offset if side == "left" else width - offset - art.width
            canvas.paste(art, (left, top), art)


def render_fallback_slide(
    brief: SceneBrief,
    style: StyleConfig,
    spec: RemotionSpec,
    work_dir: Path,
    out_mp4: Path,
    duration: float,
) -> Path:
    # Title cards are the one deliberate exception to the shared teaching board:
    # they establish the lesson on their own stage — the cast leaning in from the
    # two bottom corners, the title and subtitle surfacing in the middle.
    from .image import draw_fitted_text, draw_teaching_board

    w, h = style.layout.width, style.layout.height
    if spec.beat == "title_card":
        # NB: no local `from PIL import ...` here. Importing inside this branch
        # made Image/ImageDraw local to the WHOLE function, shadowing the
        # module-level import, so every non-title_card beat raised
        # UnboundLocalError at the shared drawing code below -- the static-slide
        # fallback this function exists to provide was broken for every beat but
        # one, turning "Remotion unavailable" into a failed scene.
        canvas = Image.new("RGB", (w, h), style.palette.background)
        draw = ImageDraw.Draw(canvas)
        pad = style.layout.padding_px
        accent = style.palette.secondary
        rule_w = round(w * 0.12)
        draw.rectangle(((w - rule_w) // 2, round(h * 0.525), (w + rule_w) // 2, round(h * 0.525) + 7),
                       fill=accent)
        draw_fitted_text(
            draw, spec.title or brief.title, {"x": pad * 2, "y": round(h * 0.30),
                               "width": w - pad * 4, "height": round(h * 0.2)},
            style, size=64, bold=True, color=style.palette.primary, align="center",
        )
        subtitle = spec.subtitle or brief.narration or brief.visual_brief
        if subtitle:
            draw_fitted_text(
                draw, subtitle, {"x": pad * 3, "y": round(h * 0.57),
                                 "width": w - pad * 6, "height": round(h * 0.1)},
                style, size=30, color=style.palette.text, align="center",
            )
        if spec.accent_label:
            draw_fitted_text(
                draw, spec.accent_label, {"x": pad * 2, "y": round(h * 0.68),
                                          "width": w - pad * 4, "height": round(h * 0.06)},
                style, size=18, color=style.palette.muted, align="center",
            )
        _paste_title_cast(canvas)
        png = work_dir / f"{brief.id}_title.png"
        png.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(png)
        out_mp4.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            ffmpeg_bin(), "-y", "-loop", "1", "-i", str(png),
            "-c:v", "libx264", "-t", str(max(2.0, duration)),
            "-pix_fmt", "yuv420p", "-vf", f"scale={w}:{h}", "-movflags", "+faststart", str(out_mp4),
        ]
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return out_mp4

    # The remaining Remotion fallback deliberately uses the same board helper
    # as image scenes, so a missing browser does not change the composition.
    img = draw_teaching_board(style, brief, include_result=False, include_character=False)
    draw = ImageDraw.Draw(img)
    board = teaching_board(style, brief)
    regions = board["regions"]
    main = regions["main"]
    result = regions["result"]

    visual_lines: list[str] = []
    if spec.beat == "formula":
        visual_lines.extend(f"• {x}" for x in spec.bullets if x)
    elif spec.beat == "compare":
        if spec.left_title:
            visual_lines.append(spec.left_title)
        visual_lines.extend(f"• {x}" for x in spec.left_items if x)
        if spec.right_title:
            visual_lines.append(spec.right_title)
        visual_lines.extend(f"• {x}" for x in spec.right_items if x)
    elif spec.beat == "steps":
        visual_lines.extend(f"{i}. {x}" for i, x in enumerate(spec.steps, 1) if x)
    elif spec.beat == "recap":
        visual_lines.extend(f"• {x}" for x in spec.bullets if x)
    elif spec.beat == "stat_row":
        visual_lines.extend(
            " ".join(str(v) for v in (item.get("value", ""), item.get("unit", ""), item.get("name", "")) if v)
            for item in spec.stats
        )
    else:
        visual_lines.extend(f"• {x}" for x in spec.bullets if x)
    if visual_lines:
        draw_fitted_text(draw, "\n".join(visual_lines), main, style, size=32, color=style.palette.text)

    result_lines = [x for x in (brief.takeaway, spec.formula if spec.beat in ("formula", "recap") else "") if x]
    if result_lines:
        draw_fitted_text(draw, "\n".join(result_lines), result, style, size=30, bold=True, color=style.palette.primary)

    png = work_dir / f"{brief.id}_slide.png"
    img.save(png)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_bin(), "-y", "-loop", "1", "-i", str(png),
        "-c:v", "libx264", "-t", str(max(2.0, duration)),
        "-pix_fmt", "yuv420p", "-vf", f"scale={w}:{h}", "-movflags", "+faststart", str(out_mp4),
    ]
    subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_mp4


_render_fallback_slide = render_fallback_slide


def remotion_available() -> bool:
    return template_root().is_dir() and bool(shutil.which("npx"))
