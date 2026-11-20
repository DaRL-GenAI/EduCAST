"""Top-level orchestration: Phase 1 (plan) -> Phase 2 (media + feedback loop).

This is the only place that knows the end-to-end flow. Each stage talks to the next
purely through schema objects, and per-segment work fans out across a thread pool.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from .config import Config
from .feedback import outer_reviewer, plan_refiner, visual_refiner
from .planner import content_writer, route
from .providers import get_provider
from .providers.base import Provider
from .renderers import get_renderer
from .renderers.base import RenderContext
from .schema import LessonPlan, Modality, NarrationAudio, Segment, VisualAsset
from .audio import narrator
from .compositor import compositor


def generate(cfg: Config) -> dict:
    cfg.ensure_dirs()
    provider = get_provider(cfg)

    plan = phase1_plan(cfg, provider)
    result = phase2_produce(cfg, provider, plan)
    return result


# ============================================================ PHASE 1 (text)
def phase1_plan(cfg: Config, provider: Provider) -> LessonPlan:
    _log("Phase 1: writing teaching content...")
    content = content_writer.write_content(provider, cfg.topic, cfg.audience)

    _log("Phase 1: routing segments to renderers...")
    plan = route.plan_lesson(provider, content)

    cfg.plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    _log(f"Phase 1: lesson plan -> {cfg.plan_path}")
    for s in plan.segments:
        _log(f"   {s.id}  [{s.modality.value:<13}] {s.title}")
    return plan


# ========================================================== PHASE 2 (media)
def phase2_produce(cfg: Config, provider: Provider, plan: LessonPlan) -> dict:
    """Nested feedback loop:

    Outer loop  (≤ max_outer_rounds, stops early when score ≥ score_threshold)
      ├─ Inner Loop 1 — Plan refinement   (narration / visual_brief edits)
      └─ Inner Loop 2 — Visual refinement (re-render broken segments)

    Caches are keyed by segment id; only dirty segments are re-produced each round.
    """
    audio_cache: dict[str, NarrationAudio] = {}
    visual_cache: dict[str, VisualAsset] = {}
    draft_path = None

    for outer_rnd in range(cfg.max_outer_rounds + 1):
        # --- render all dirty segments ---
        dirty = {s.id for s in plan.segments if s.id not in visual_cache}
        if dirty:
            if outer_rnd > 0:
                _log(f"Outer round {outer_rnd}: re-producing {len(dirty)} segment(s)")
            _produce_assets(cfg, provider, plan, dirty, audio_cache, visual_cache)

        # --- composite ---
        is_last = (outer_rnd == cfg.max_outer_rounds)
        draft_name = "final.mp4" if is_last else f"draft_r{outer_rnd}.mp4"
        draft_path = cfg.video_dir / draft_name
        _log(f"Compositing → {draft_path}")
        compositor.assemble(
            [visual_cache[s.id] for s in plan.segments],
            [audio_cache[s.id] for s in plan.segments],
            draft_path,
        )

        if not cfg.use_feedback or is_last:
            break

        # --- outer review ---
        _log(f"Outer review (round {outer_rnd})…")
        rev = outer_reviewer.review(provider, plan, draft_path)
        _log(
            f"  score={rev.overall_score:.1f}  "
            f"content_issues={len(rev.content_issues)}  "
            f"visual_issues={len(rev.visual_issues)}"
        )
        (cfg.run_dir / f"review_r{outer_rnd}.json").write_text(
            rev.model_dump_json(indent=2), encoding="utf-8"
        )

        # early-stop when quality is good enough
        if rev.overall_score >= cfg.score_threshold:
            _log(f"Score {rev.overall_score:.1f} ≥ {cfg.score_threshold} — done.")
            draft_path = _finalize(cfg, draft_path)
            break

        if not rev.needs_plan_fix and not rev.needs_visual_fix:
            _log("No actionable issues; finalizing.")
            draft_path = _finalize(cfg, draft_path)
            break

        # --- Inner Loop 1: plan refinement (narration / visual_brief) ---
        if rev.needs_plan_fix:
            _log(f"  Inner Loop 1 — plan refinement ({len(rev.content_issues)} issues)")
            dirty_full, dirty_visual_only = plan_refiner.refine(
                provider, plan, rev.content_issues
            )
            for sid in dirty_full:          # narration changed → re-TTS + re-render
                audio_cache.pop(sid, None)
                visual_cache.pop(sid, None)
            for sid in dirty_visual_only:   # brief changed only → re-render only
                visual_cache.pop(sid, None)
            cfg.plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

        # --- Inner Loop 2: visual refinement (re-render broken segments) ---
        if rev.needs_visual_fix:
            _log(f"  Inner Loop 2 — visual refinement ({len(rev.visual_issues)} issues)")
            dirty_visual = visual_refiner.refine(provider, plan, rev.visual_issues)
            for sid in dirty_visual:        # brief updated → re-render only
                visual_cache.pop(sid, None)

    return {"plan_path": str(cfg.plan_path), "video_path": str(draft_path)}


def _produce_assets(cfg, provider, plan, dirty, audio_cache, visual_cache):
    """Narrate + render every dirty segment, in parallel."""
    todo = [s for s in plan.segments if s.id in dirty]
    if not todo:
        return

    def work(seg: Segment):
        audio = narrator.narrate(provider, seg, cfg.audio_dir)
        visual = _render_segment(cfg, provider, seg, audio)
        return seg.id, audio, visual

    if cfg.parallel:
        with ThreadPoolExecutor(max_workers=cfg.max_workers) as ex:
            results = list(ex.map(work, todo))
    else:
        results = [work(s) for s in todo]

    for sid, audio, visual in results:
        audio_cache[sid] = audio
        visual_cache[sid] = visual


def _render_segment(cfg, provider, seg: Segment, audio: NarrationAudio) -> VisualAsset:
    """Dispatch to the planned renderer; degrade gracefully on failure.

    Fallback order is planned -> concept_image -> slide. concept_image comes first so
    that a failed animation does NOT introduce a stray slide on a non-recap segment
    (slides are reserved for the final summary). Slide is the last-resort emergency.
    """
    ctx = RenderContext(
        cfg=cfg, provider=provider, out_dir=cfg.assets_dir, audio_seconds=audio.duration
    )
    chain = [seg.modality]
    for m in (Modality.CONCEPT_IMAGE, Modality.SLIDE):
        if m not in chain:
            chain.append(m)

    last_err: Exception | None = None
    for i, modality in enumerate(chain):
        try:
            asset = get_renderer(modality).render(seg, ctx)
            if i > 0:
                _log(f"   {seg.id}: {seg.modality.value} failed; fell back to {modality.value}")
                seg.modality = modality
            return asset
        except Exception as e:  # NotImplementedError included
            last_err = e
    raise last_err  # all renderers failed for this segment


def _finalize(cfg: Config, draft_path):
    final = cfg.video_dir / "final.mp4"
    if str(draft_path) != str(final):
        import shutil

        shutil.copy(draft_path, final)
    return final


def _log(msg: str) -> None:
    print(f"[teachgen] {msg}", flush=True)
