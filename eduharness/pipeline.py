"""End-to-end EduHarness orchestration."""

from __future__ import annotations

import json
import time
from pathlib import Path

from .config import Config
from .providers import UsageTracker, get_provider
from .schema import HarnessRequest, LessonBlueprint, Manifest, PreparedScene, RenderedScene
from .stage1 import main_agent
from .stage2 import repair_router, workflow
from .stage3 import bundler


def run(cfg: Config) -> dict:
    """Full pipeline: Stage1 → Stage2 → Stage3."""
    cfg.ensure_dirs()
    started = time.time()
    (cfg.run_dir / "request.json").write_text(
        cfg.request.model_dump_json(indent=2), encoding="utf-8"
    )
    usage = UsageTracker(cfg.usage_path)
    provider = get_provider(cfg, usage)

    print("=== Stage 1: Main Agent (plan + style) ===", flush=True)
    blueprint = stage1(cfg, provider)

    print("=== Stage 2: Executor + guards + VLM Reviewer ===", flush=True)
    rendered = stage2(cfg, provider, blueprint)

    print("=== Stage 3: EduBundle + Interactive Player ===", flush=True)
    manifest = stage3(cfg, blueprint, rendered)

    passed = sum(1 for r in rendered if r.review_passed)
    result = {
        "run_dir": str(cfg.run_dir),
        "blueprint": str(cfg.blueprint_path),
        "manifest": str(cfg.manifest_path),
        "player": str(cfg.bundle_dir / "index.html"),
        "scenes": len(blueprint.scenes),
        "scenes_passed": passed,
        "timeline": len(manifest.timeline),
        "total_duration": round(manifest.total_duration, 1),
        "elapsed_seconds": round(time.time() - started, 1),
        "usage": usage.summary(),
    }
    (cfg.run_dir / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Usage: {usage.format_summary()}", flush=True)
    print("Done:", json.dumps({k: v for k, v in result.items() if k != "usage"}), flush=True)
    return result


def stage1(cfg: Config, provider=None) -> LessonBlueprint:
    cfg.ensure_dirs()
    provider = provider or get_provider(cfg, UsageTracker(cfg.usage_path))
    request = cfg.request.model_copy(update={
        "enable_image": cfg.enable_image, "enable_narration": cfg.enable_narration,
    })
    blueprint = main_agent.plan_lesson(provider, request)
    cfg.blueprint_path.write_text(blueprint.model_dump_json(indent=2), encoding="utf-8")
    cfg.style_path.write_text(blueprint.style.model_dump_json(indent=2), encoding="utf-8")
    print(f"Blueprint → {cfg.blueprint_path}", flush=True)
    for s in blueprint.scenes:
        extra = f" ← overlays {s.trigger_scene_id}@{s.trigger_at_seconds}s" if s.trigger_scene_id else ""
        print(f"  {s.id:24} [{s.scene_type.value:11}] {s.title}{extra}", flush=True)
    return blueprint


def stage2(
    cfg: Config,
    provider=None,
    blueprint: LessonBlueprint | None = None,
) -> list[RenderedScene]:
    """One-machine loop over prepare → render → review with targeted repairs."""
    cfg.ensure_dirs()
    provider = provider or get_provider(cfg, UsageTracker(cfg.usage_path))
    blueprint = blueprint or _load_blueprint(cfg)
    rendered = workflow.run_repair_loop(cfg, provider, blueprint)
    print(f"Rendered → {cfg.rendered_path}", flush=True)
    return rendered


def stage2_prepare(
    cfg: Config,
    provider=None,
    blueprint: LessonBlueprint | None = None,
    *,
    force: bool = False,
) -> list[PreparedScene]:
    """`force` re-asks the model for every scene spec — use it after changing the
    authoring prompt or the scene kit. Narration is still reused from the cache."""
    cfg.ensure_dirs()
    provider = provider or get_provider(cfg, UsageTracker(cfg.usage_path))
    blueprint = blueprint or _load_blueprint(cfg)
    previous = workflow.load_prepared(cfg) if workflow.has_prepared_checkpoint(cfg) else None
    stale = workflow.stale_prepared_scene_ids(cfg, blueprint, previous)
    repairs: dict = {}
    if force:
        print(f"Forced re-preparation of {len(blueprint.scenes)} scenes.", flush=True)
        return workflow.prepare_all(cfg, provider, blueprint, previous=previous)
    if workflow.has_rendered_checkpoint(cfg):
        rendered = workflow.load_rendered(cfg)
        repairs = repair_router.repairs_from_rendered(rendered, include_review_errors=False)
        for scene_id in stale:
            repairs.pop(scene_id, None)
        if not repairs and previous and not stale:
            print("All scenes already passed review (or only need re-review); prepare checkpoint unchanged.")
            return previous
    if previous and repairs:
        by_id = {item.scene_id: item for item in previous}
        exhausted = {
            scene_id
            for scene_id in repairs
            if by_id.get(scene_id)
            and by_id[scene_id].attempt >= max(0, cfg.max_review_rounds - 1)
        }
        rendered_by_id = {r.scene_id: r for r in workflow.load_rendered(cfg)} if workflow.has_rendered_checkpoint(cfg) else {}
        for scene_id in exhausted:
            item = rendered_by_id.get(scene_id)
            if item is not None:
                workflow.write_hitl(cfg, item, "Review retry budget exhausted.")
            repairs.pop(scene_id, None)
        if not repairs and not stale:
            print("Review retry budget exhausted; checkpoints unchanged.")
            return previous
    if repairs:
        targets = set(repairs) | stale
    elif previous:
        prepared_ids = {item.scene_id for item in previous}
        targets = stale | {scene.id for scene in blueprint.scenes if scene.id not in prepared_ids}
        if not targets:
            print("All prepared scene checkpoints are present; nothing to prepare.", flush=True)
            return previous
    else:
        targets = None
    result = workflow.prepare_all(
        cfg, provider, blueprint, previous=previous, only_scene_ids=targets, repairs_by_id=repairs
    )
    print(f"Prepared → {cfg.prepared_path}", flush=True)
    return result


def stage2_render(
    cfg: Config,
    blueprint: LessonBlueprint | None = None,
    *,
    force: bool = False,
    repair_crashes: bool = True,
) -> list[RenderedScene]:
    """Render prepared checkpoints. `force` re-renders every scene — use it after
    editing the style board, and re-run `2-review` afterwards: the stored verdicts
    describe the old look, so they are dropped here rather than silently reused."""
    cfg.ensure_dirs()
    blueprint = blueprint or _load_blueprint(cfg)
    prepared = workflow.load_prepared(cfg)
    previous = workflow.load_rendered(cfg) if workflow.has_rendered_checkpoint(cfg) else None
    previous_by_id = {item.scene_id: item for item in previous or []}
    scenes_by_id = {scene.id: scene for scene in blueprint.scenes}
    if force:
        targets = {item.scene_id for item in prepared}
        previous = None
        print(f"Forced re-render of {len(targets)} scenes; prior review verdicts dropped.", flush=True)
    else:
        targets = {
            item.scene_id
            for item in prepared
            if item.scene_id not in previous_by_id
            or not previous_by_id[item.scene_id].review_passed
            or previous_by_id[item.scene_id].debug.get("prepared_attempt") != item.attempt
            or not workflow.rendered_is_current(
                cfg,
                scenes_by_id[item.scene_id],
                blueprint,
                item,
                previous_by_id.get(item.scene_id),
            )
        }
    # A provider is used only when generated code crashes: one targeted repair call
    # beats shipping a placeholder scene. No key (the Colab flow) simply skips it.
    repairer = None
    if repair_crashes and cfg.api_key:
        try:
            repairer = get_provider(cfg, UsageTracker(cfg.usage_path))
        except Exception as exc:
            print(f"  [render] traceback repair unavailable: {exc}", flush=True)
    result = workflow.render_all(cfg, blueprint, prepared, previous=previous,
                                 only_scene_ids=targets, provider=repairer)
    print(f"Rendered locally → {cfg.rendered_path}", flush=True)
    return result


def stage2_review(
    cfg: Config,
    provider=None,
    blueprint: LessonBlueprint | None = None,
) -> list[RenderedScene]:
    cfg.ensure_dirs()
    provider = provider or get_provider(cfg, UsageTracker(cfg.usage_path))
    blueprint = blueprint or _load_blueprint(cfg)
    current = workflow.load_rendered(cfg)
    targets = {item.scene_id for item in current if not item.review_passed}
    result = workflow.review_all(cfg, provider, blueprint, current, only_scene_ids=targets)
    for item in result:
        if item.review_error:
            workflow.write_hitl(cfg, item, "Reviewer unavailable; scene could not be audited.")
    print(f"Reviewed → {cfg.rendered_path}", flush=True)
    return result


def stage3(
    cfg: Config,
    blueprint: LessonBlueprint | None = None,
    rendered: list[RenderedScene] | None = None,
) -> Manifest:
    cfg.ensure_dirs()
    blueprint = blueprint or _load_blueprint(cfg)
    if rendered is None:
        rendered = workflow.load_rendered(cfg)
    manifest = bundler.build_bundle(
        cfg.run_dir,
        blueprint,
        rendered,
        bundle_id=cfg.request.request_id or "edubundle",
        allow_unreviewed=cfg.request.allow_unreviewed_bundle,
    )
    print(f"Bundle → {cfg.bundle_dir}", flush=True)
    print(f"Player → {cfg.bundle_dir / 'index.html'}", flush=True)
    return manifest


def load_request(path: str | Path) -> HarnessRequest:
    return HarnessRequest.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _load_blueprint(cfg: Config) -> LessonBlueprint:
    return LessonBlueprint.model_validate_json(cfg.blueprint_path.read_text(encoding="utf-8"))
