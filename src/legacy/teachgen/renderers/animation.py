"""`animation` renderer — drives code2video (code2video/agent.py) at single-segment grain.

teachgen owns the outline, so we DO NOT call agent.GENERATE_VIDEO() (its top-level
multi-section orchestration). Instead, per segment, we:

  1. Convert the segment into code2video's `Section` shape (short on-screen lecture
     lines, each paired with an animation description) via the Provider.
  2. Build a code2video RunConfig whose `api` callable is a shim over our Provider,
     so the whole system still needs only one OpenAI key. code2video's own Gemini
     video-feedback loop is disabled (use_feedback=False) — teachgen's outer reviewer
     covers holistic feedback; the inner Manim bug-fix loop (ScopeRefine) stays on.
  3. Run generate_section_code() then render_section(), which renders Manim and runs
     the self-repair loop, landing an .mp4 in agent.section_videos[seg.id].
  4. Copy that clip into teachgen's assets dir and return it as a VisualAsset(video).

If Manim isn't installed or the render ultimately fails, this raises — and the
pipeline transparently falls back to a slide for that segment.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from pydantic import BaseModel, Field

from ..schema import Modality, Segment, VisualAsset
from .base import RenderContext

# Code2Video renders at -ql (854x480 @ 15fps); the compositor upscales to 1080p.

STORYBOARD_SYSTEM = """\
You convert one teaching segment into a Manim storyboard for a 2D animation.
Produce SHORT on-screen lecture lines (each <= 8 words) and, for EACH line, one
concrete animation description of what should appear/move on the right side of the
screen to illustrate it. Keep it to 2-5 lines. The two lists MUST be the same length
and aligned by index. Describe only simple 2D vector graphics (shapes, arrows, labels,
graphs) — no 3D, no external images. Be specific and visual.
"""


class _AnimSpec(BaseModel):
    lecture_lines: list[str] = Field(..., description="2-5 short on-screen lines")
    animations: list[str] = Field(..., description="One animation description per line")


class AnimationRenderer:
    modality = Modality.ANIMATION

    def render(self, seg: Segment, ctx: RenderContext) -> VisualAsset:
        agent_mod, base_class = _load_code2video(ctx.cfg.repo_root)

        spec = self._storyboard(ctx, seg)
        section = agent_mod.Section(
            id=seg.id,
            title=seg.title,
            lecture_lines=spec.lecture_lines,
            animations=spec.animations,
        )

        cfg = agent_mod.RunConfig(
            api=_provider_api(ctx),     # route code2video's LLM calls through our Provider
            use_feedback=False,         # disable code2video's Gemini video loop
            use_assets=False,
            max_code_token_length=10000,
            max_regenerate_tries=2,     # outer: regenerate whole scene
            max_fix_bug_tries=3,        # inner: ScopeRefine bug fixes per attempt
        )

        # code2video hard-codes a "CASES" layout and resolves json_files relative to it.
        folder = ctx.cfg.repo_root / "code2video" / "CASES" / f"tg_{ctx.cfg.run_dir.name}"
        agent = agent_mod.TeachingVideoAgent(
            idx=0, knowledge_point=seg.title, folder=folder, cfg=cfg
        )

        # Force fresh code each round (code2video reuses an existing <id>.py otherwise).
        code_file = agent.output_dir / f"{seg.id}.py"
        if code_file.exists():
            code_file.unlink()

        agent.generate_section_code(section, attempt=1)
        ok = agent.render_section(section)
        mp4 = agent.section_videos.get(seg.id)
        if not ok or not mp4 or not Path(mp4).exists():
            raise RuntimeError(f"code2video failed to render {seg.id}")

        out = ctx.out_dir / f"{seg.id}.mp4"
        shutil.copy(mp4, out)
        return VisualAsset(
            segment_id=seg.id, kind="video", path=str(out), duration=_duration(out)
        )

    def _storyboard(self, ctx: RenderContext, seg: Segment) -> _AnimSpec:
        prompt = (
            f"Title: {seg.title}\n"
            f"Narration: {seg.narration}\n"
            f"Visual brief: {seg.visual_brief}\n"
            f"Target duration: ~{seg.target_seconds or 12:.0f}s\n\n"
            "Produce the aligned lecture_lines and animations."
        )
        return ctx.provider.chat_json(
            prompt, _AnimSpec, system=STORYBOARD_SYSTEM, max_tokens=1500
        )


# --------------------------------------------------------------------- helpers
def _provider_api(ctx: RenderContext):
    """A code2video-compatible `api` callable backed by teachgen's Provider.

    code2video calls `response, usage = api(prompt, max_tokens=...)` and reads
    `response.choices[0].message.content`. We mimic just that shape.
    """
    provider = ctx.provider

    class _Resp:
        def __init__(self, content):
            self.choices = [type("C", (), {"message": type("M", (), {"content": content})})]

    def api(prompt, max_tokens=8000, **_):
        text = provider.chat(prompt, max_tokens=min(max_tokens, 8000))
        return _Resp(text), {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    return api


def _load_code2video(repo_root: Path):
    """Lazy-import code2video/agent.py (pulls Manim). repo_root and code2video/ must import."""
    for p in (str(repo_root), str(repo_root / "code2video")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import agent  # noqa: E402  (code2video/agent.py)
    from prompts import base_class  # noqa: E402  (repo_root/prompts)

    return agent, base_class


def _duration(path: Path) -> float:
    try:
        from ..mpcompat import VideoFileClip

        clip = VideoFileClip(str(path))
        d = float(clip.duration)
        clip.close()
        return d
    except Exception:
        return 0.0
