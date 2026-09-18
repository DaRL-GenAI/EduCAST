"""Checkpointed Stage 2: API preparation → local rendering → API review.

Three idempotent passes that all persist to <run_dir>/prepared_scenes.json and
<run_dir>/rendered_scenes.json, so the same code serves the one-machine loop
(`run_repair_loop`) and the Colab-hybrid CLI stages (`2-prepare`, `2-render`,
`2-review`). Scenes are processed in parallel; results keep blueprint order.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, TypeVar

from ..config import Config
from ..presentation import character_asset_path
from ..providers.base import Provider
from ..schema import (
    GuardFinding,
    GuardReport,
    InteractiveParams,
    LayoutSpec,
    LessonBlueprint,
    PreparedScene,
    RenderedScene,
    SceneBrief,
    SceneRepair,
    SceneType,
)
from . import media, narration, repair_router, reviewer
from .adapters import image as image_adapter
from .adapters import interactive as interactive_adapter
from .adapters import manim as manim_adapter
from .adapters import remotion as remotion_adapter

T = TypeVar("T")
_CHECKPOINT_LOCK = threading.Lock()

# Bump this when checkpoint semantics change in a way that is not captured by
# the source/artifact digests below. Legacy checkpoints without a fingerprint
# intentionally miss closed and are rebuilt once.
_FINGERPRINT_VERSION = 1


# --------------------------------------------------------------------------- helpers
def _parallel(cfg: Config, scenes: list[SceneBrief], fn: Callable[[SceneBrief], T]) -> list[T]:
    workers = max(1, min(cfg.parallel, len(scenes) or 1))
    if workers == 1:
        return [fn(scene) for scene in scenes]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(fn, scenes))


def feedback_text(repair: SceneRepair | None) -> str:
    return repair.feedback_text() if repair else ""


def _sha256_json(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_digest(path: Path | None) -> str:
    if path is None:
        return "missing"
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "missing"


def _module_digest(module) -> str:
    raw = getattr(module, "__file__", None)
    return _file_digest(Path(raw)) if raw else "missing"


def _adapter_for(scene_type: SceneType):
    return {
        SceneType.IMAGE: image_adapter,
        SceneType.MANIM: manim_adapter,
        SceneType.REMOTION: remotion_adapter,
        SceneType.INTERACTIVE: interactive_adapter,
    }[scene_type]


def prepare_fingerprint(cfg: Config, scene: SceneBrief, blueprint: LessonBlueprint) -> str:
    """Hash every input that can change a prepared spec, image, or narration."""
    adapter = _adapter_for(scene.scene_type)
    return _sha256_json({
        "version": _FINGERPRINT_VERSION,
        "phase": "prepare",
        "scene": scene.model_dump(mode="json"),
        "lesson": {
            "topic": blueprint.topic,
            "audience": blueprint.audience,
            "learning_goal": blueprint.learning_goal,
            "objectives": blueprint.objectives,
        },
        "style": blueprint.style.model_dump(mode="json"),
        "config": {
            "enable_image": cfg.enable_image,
            "enable_narration": cfg.enable_narration,
            "enable_manim": cfg.request.enable_manim,
            "enable_remotion": cfg.request.enable_remotion,
            "language": cfg.request.language,
            "voice": cfg.voice,
            "text_model": cfg.models.text,
            "image_model": cfg.models.image,
            "image_prompt_model": cfg.models.image_prompt,
            "image_quality": os.environ.get("EDUHARNESS_IMAGE_QUALITY", "high"),
            "tts_model": cfg.models.tts,
            "reasoning_effort": cfg.models.reasoning_effort,
            "max_completion_tokens": cfg.models.max_completion_tokens,
        },
        "sources": {
            "schema": _file_digest(Path(__file__).resolve().parents[1] / "schema.py"),
            "adapter": _module_digest(adapter),
            "repair_router": _module_digest(repair_router),
            "narration": _module_digest(narration),
        },
    })


def prepared_is_current(
    cfg: Config,
    scene: SceneBrief,
    blueprint: LessonBlueprint,
    prepared: PreparedScene | None,
) -> bool:
    if not (
        prepared is not None
        and prepared.scene_type == scene.scene_type
        and prepared.debug.get("prepare_fingerprint") == prepare_fingerprint(cfg, scene, blueprint)
        and not prepared.debug.get("prepare_error")
    ):
        return False
    artifact_path = prepared.asset_path if scene.scene_type == SceneType.IMAGE else prepared.spec_path
    if not artifact_path or not (cfg.run_dir / artifact_path).is_file():
        return False
    if scene.narration.strip() and cfg.enable_narration:
        if not prepared.narration_path or not (cfg.run_dir / prepared.narration_path).is_file():
            return False
    return True


def stale_prepared_scene_ids(
    cfg: Config,
    blueprint: LessonBlueprint,
    prepared: list[PreparedScene] | None,
) -> set[str]:
    by_id = {item.scene_id: item for item in prepared or []}
    stale: set[str] = set()
    for scene in blueprint.scenes:
        item = by_id.get(scene.id)
        if item is None:
            stale.add(scene.id)
            continue
        if prepared_is_current(cfg, scene, blueprint, item):
            continue
        # A legacy per-scene checkpoint with no artifact is commonly a deliberate
        # partial-prepare marker. Keep it as a marker so recovery can request only
        # genuinely missing scene ids; any checkpoint with an artifact (or an
        # explicit error) is treated as stale and rebuilt.
        if (
            item.debug.get("prepare_fingerprint")
            or item.debug.get("prepare_error")
            or item.spec_path
            or item.asset_path
            or item.narration_path
        ):
            stale.add(scene.id)
    return stale


def _prepared_artifacts(cfg: Config, prepared: PreparedScene) -> dict[str, str]:
    return {
        field: _file_digest(cfg.run_dir / value) if value else "none"
        for field, value in (
            ("spec", prepared.spec_path),
            ("asset", prepared.asset_path),
            ("narration", prepared.narration_path),
        )
    }


def render_fingerprint(
    cfg: Config,
    scene: SceneBrief,
    blueprint: LessonBlueprint,
    prepared: PreparedScene,
) -> str:
    """Hash prepared bytes plus local renderer/template inputs."""
    adapter = _adapter_for(scene.scene_type)
    sources: dict[str, str] = {
        "schema": _file_digest(Path(__file__).resolve().parents[1] / "schema.py"),
        "adapter": _module_digest(adapter),
        "media": _module_digest(media),
        # Rendering/retry policy lives in this module too. Include it so an
        # existing checkpoint cannot silently bypass a layout fix after an
        # upgrade of the Stage 2 workflow.
        "workflow": _file_digest(Path(__file__).resolve()),
    }
    if scene.scene_type == SceneType.REMOTION:
        template = cfg.repo_root / "remotion_template"
        for rel in ("package-lock.json", "src/Root.tsx", "src/SceneBeat.tsx", "remotion.config.ts"):
            sources[f"remotion/{rel}"] = _file_digest(template / rel)
        sources["remotion_version"] = str(getattr(remotion_adapter, "REMOTION_VERSION", "unknown"))
    elif scene.scene_type == SceneType.INTERACTIVE:
        sources["interactive_runtime"] = _file_digest(
            Path(interactive_adapter.__file__).resolve().parents[2] / "stage3" / "interactive_runtime.js"
        )
    return _sha256_json({
        "version": _FINGERPRINT_VERSION,
        "phase": "render",
        "scene": scene.model_dump(mode="json"),
        "style": blueprint.style.model_dump(mode="json"),
        "prepare_fingerprint": prepared.debug.get("prepare_fingerprint"),
        "prepared_artifacts": _prepared_artifacts(cfg, prepared),
        "config": {
            "manim_quality": cfg.manim_quality,
            "manim_container_image": cfg.manim_container_image,
            "ambient_particles": getattr(manim_adapter, "AMBIENT_PARTICLES", None),
        },
        "sources": sources,
    })


def rendered_is_current(
    cfg: Config,
    scene: SceneBrief,
    blueprint: LessonBlueprint,
    prepared: PreparedScene | None,
    rendered: RenderedScene | None,
) -> bool:
    return bool(
        prepared is not None
        and rendered is not None
        and rendered.scene_type == scene.scene_type
        and rendered.debug.get("render_fingerprint")
        == render_fingerprint(cfg, scene, blueprint, prepared)
    )


def stale_rendered_scene_ids(
    cfg: Config,
    blueprint: LessonBlueprint,
    prepared: list[PreparedScene] | None,
    rendered: list[RenderedScene] | None,
) -> set[str]:
    prepared_by_id = {item.scene_id: item for item in prepared or []}
    rendered_by_id = {item.scene_id: item for item in rendered or []}
    return {
        scene.id for scene in blueprint.scenes
        if not rendered_is_current(
            cfg, scene, blueprint, prepared_by_id.get(scene.id), rendered_by_id.get(scene.id)
        )
    }


def _log(scene_id: str, message: str) -> None:
    print(f"  [{scene_id}] {message}", flush=True)


def load_prepared(cfg: Config) -> list[PreparedScene]:
    values = _load_checkpoint_values(cfg, "prepared")
    return [PreparedScene.model_validate(item) for item in values]


def load_rendered(cfg: Config) -> list[RenderedScene]:
    values = _load_checkpoint_values(cfg, "rendered")
    return [RenderedScene.model_validate(item) for item in values]


def _write_models(path: Path, values: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps([item.model_dump(mode="json") for item in values], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(temp, path)


def _checkpoint_dir(cfg: Config, kind: str) -> Path:
    return cfg.run_dir / ".studio" / "checkpoints" / kind


def _checkpoint_path(cfg: Config, kind: str, scene_id: str) -> Path:
    safe = "".join(char if char.isalnum() or char in "-_" else "_" for char in scene_id)
    return _checkpoint_dir(cfg, kind) / f"{safe}.json"


def _update_run_state(cfg: Config, stage: str, status: str, **extra) -> None:
    """Persist a small phase heartbeat independently of aggregate checkpoints."""
    path = cfg.run_dir / ".studio" / "run_state.json"
    with _CHECKPOINT_LOCK:
        current: dict = {}
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    current = raw
            except (OSError, ValueError, TypeError):
                current = {}
        current.update({
            "stage": stage,
            "status": status,
            "heartbeat_at": time.time(),
            **extra,
        })
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(current, indent=2), encoding="utf-8")
        os.replace(temp, path)


def _write_scene_checkpoint(cfg: Config, kind: str, value, *, stage: str | None = None) -> None:
    path = _checkpoint_path(cfg, kind, value.scene_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(value.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    with _CHECKPOINT_LOCK:
        os.replace(temp, path)
    _update_run_state(
        cfg,
        stage or ("2-prepare" if kind == "prepared" else "2-render"),
        "running",
        **{"completed_" + kind: len(list(_checkpoint_dir(cfg, kind).glob("*.json")))},
    )


def _load_checkpoint_values(cfg: Config, kind: str) -> list[dict]:
    """Merge the legacy aggregate with per-scene records written by workers."""
    aggregate = cfg.prepared_path if kind == "prepared" else cfg.rendered_path
    values: dict[str, dict] = {}
    if aggregate.is_file():
        try:
            raw = json.loads(aggregate.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                values.update({str(item.get("scene_id")): item for item in raw if isinstance(item, dict) and item.get("scene_id")})
        except (OSError, ValueError, TypeError):
            pass
    directory = _checkpoint_dir(cfg, kind)
    if directory.is_dir():
        for path in sorted(directory.glob("*.json")):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            if isinstance(item, dict) and item.get("scene_id"):
                values[str(item["scene_id"])] = item
    return list(values.values())


def has_prepared_checkpoint(cfg: Config) -> bool:
    return cfg.prepared_path.is_file() or (
        _checkpoint_dir(cfg, "prepared").is_dir()
        and any(_checkpoint_dir(cfg, "prepared").glob("*.json"))
    )


def has_rendered_checkpoint(cfg: Config) -> bool:
    return cfg.rendered_path.is_file() or (
        _checkpoint_dir(cfg, "rendered").is_dir()
        and any(_checkpoint_dir(cfg, "rendered").glob("*.json"))
    )


def write_hitl(cfg: Config, item: RenderedScene, reason: str) -> None:
    path = cfg.run_dir / "debug" / f"{item.scene_id}_HITL.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = [reason, ""]
    if item.repair is not None:
        body.append(item.repair.feedback_text())
    elif item.review_notes:
        body.append(item.review_notes)
    path.write_text("\n".join(body) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- prepare
def prepare_all(
    cfg: Config,
    provider: Provider,
    blueprint: LessonBlueprint,
    *,
    previous: list[PreparedScene] | None = None,
    only_scene_ids: set[str] | None = None,
    feedback_by_id: dict[str, str] | None = None,
    repairs_by_id: dict[str, SceneRepair] | None = None,
) -> list[PreparedScene]:
    """Run only model/API work (specs, images, narration) and persist portable checkpoints."""
    _update_run_state(cfg, "2-prepare", "running", total=len(blueprint.scenes))
    prior = {item.scene_id: item for item in previous or []}
    repairs = dict(repairs_by_id or {})
    for scene_id, text in (feedback_by_id or {}).items():
        if scene_id not in repairs and text:
            repairs[scene_id] = SceneRepair(
                scene_id=scene_id, passed=False, score=0.0, severity="major",
                fix_action="re_render", blocking_issues=[text],
            ).finalize()

    def work(scene: SceneBrief) -> PreparedScene:
        p = prior.get(scene.id)
        current = prepared_is_current(cfg, scene, blueprint, p)
        repair = repairs.get(scene.id)
        if only_scene_ids is not None and scene.id not in only_scene_ids and p is not None and current:
            _write_scene_checkpoint(cfg, "prepared", p)
            return p
        if repair is not None:
            repair = repair.model_copy(update={"scene_type": scene.scene_type})
        attempt = (p.attempt + 1) if (p is not None and repair is not None) else 0
        fingerprint = prepare_fingerprint(cfg, scene, blueprint)
        started = time.time()
        _log(scene.id, f"prepare ({scene.scene_type.value}) attempt={attempt}"
                       + (" with repair" if repair else ""))
        try:
            result = _prepare_one(cfg, provider, blueprint, scene, p, repair, attempt)
        except Exception as exc:
            # One scene's API failure must not sink the round; render/review will
            # report it and the next round re-prepares only this scene.
            (cfg.run_dir / "work" / scene.id).mkdir(parents=True, exist_ok=True)
            (cfg.run_dir / "work" / scene.id / "prepare_error.txt").write_text(
                traceback.format_exc(), encoding="utf-8"
            )
            _log(scene.id, f"prepare FAILED: {exc}")
            result = PreparedScene(
                scene_id=scene.id, scene_type=scene.scene_type, attempt=attempt,
                feedback=feedback_text(repair), repair=repair,
                debug={
                    "prepare_error": str(exc)[:500], "repair_mode": "failed",
                    "prepare_fingerprint": fingerprint,
                },
            )
            _write_scene_checkpoint(cfg, "prepared", result)
            return result
        result.debug["prepare_fingerprint"] = fingerprint
        _log(scene.id, f"prepared in {time.time() - started:.0f}s → {result.debug.get('repair_mode', 'generated')}")
        _write_scene_checkpoint(cfg, "prepared", result)
        return result

    output = _parallel(cfg, blueprint.scenes, work)
    _write_models(cfg.prepared_path, output)
    _update_run_state(cfg, "2-prepare", "complete", completed_prepared=len(output))
    return output


def _prepare_one(
    cfg: Config,
    provider: Provider,
    blueprint: LessonBlueprint,
    scene: SceneBrief,
    prior: PreparedScene | None,
    repair: SceneRepair | None,
    attempt: int,
) -> PreparedScene:
    work = cfg.run_dir / "work" / scene.id
    work.mkdir(parents=True, exist_ok=True)
    narration_path, narration_seconds, key = narration.prepare_narration(
        cfg, provider, scene, work, prior
    )
    prepared = repair_router.prepare_with_repair(
        provider=provider,
        scene=scene,
        style=blueprint.style,
        work=work,
        run_dir=cfg.run_dir,
        prior=prior,
        repair=repair,
        attempt=attempt,
        narration_seconds=narration_seconds,
        image_prompt_model=cfg.models.image_prompt,
        audience=blueprint.audience,
        language=cfg.request.language,
        opener=bool(blueprint.scenes) and scene.id == blueprint.scenes[0].id,
    )
    prepared.narration_path = narration_path
    prepared.narration_seconds = narration_seconds
    if key:
        prepared.debug["narration_key"] = key
    return prepared


# --------------------------------------------------------------------------- render
def render_all(
    cfg: Config,
    blueprint: LessonBlueprint,
    prepared: list[PreparedScene] | None = None,
    *,
    previous: list[RenderedScene] | None = None,
    only_scene_ids: set[str] | None = None,
    provider: Provider | None = None,
) -> list[RenderedScene]:
    """Render prepared checkpoints locally. `provider` is optional and only used
    for a one-shot Manim traceback repair (skipped in the offline Colab flow)."""
    _update_run_state(cfg, "2-render", "running")
    prepared = prepared or load_prepared(cfg)
    by_prepared = {item.scene_id: item for item in prepared}
    prior = {item.scene_id: item for item in previous or []}

    def work(scene: SceneBrief) -> RenderedScene:
        item = by_prepared.get(scene.id)
        old = prior.get(scene.id)
        current = rendered_is_current(cfg, scene, blueprint, item, old)
        if (
            only_scene_ids is not None
            and scene.id not in only_scene_ids
            and current
            and old is not None
        ):
            _write_scene_checkpoint(cfg, "rendered", old)
            return old
        if item is None:
            result = _render_error(scene, "No prepared checkpoint")
            _write_scene_checkpoint(cfg, "rendered", result)
            return result
        if item.debug.get("prepare_error"):
            result = _render_error(scene, f"Preparation failed: {item.debug['prepare_error']}", attempt=item.attempt)
            _write_scene_checkpoint(cfg, "rendered", result)
            return result
        started = time.time()
        _log(scene.id, f"render ({scene.scene_type.value})")
        try:
            result = _render_one(cfg, blueprint, scene, item, provider)
            result = _retry_on_guard_blockers(cfg, blueprint, scene, item, result, provider)
        except Exception as exc:
            (cfg.run_dir / "work" / scene.id / "render_error.txt").write_text(
                traceback.format_exc(), encoding="utf-8"
            )
            _log(scene.id, f"render FAILED: {exc}")
            result = _render_error(scene, str(exc), attempt=item.attempt)
            _write_scene_checkpoint(cfg, "rendered", result)
            return result
        result.debug["prepared_attempt"] = item.attempt
        result.debug["render_fingerprint"] = render_fingerprint(cfg, scene, blueprint, item)
        _log(scene.id, f"rendered in {time.time() - started:.0f}s mode={result.render_mode}"
                       + (f" guard={len(result.guard.findings)}" if result.guard.findings else ""))
        _write_scene_checkpoint(cfg, "rendered", result)
        return result

    output = _parallel(cfg, blueprint.scenes, work)
    _write_models(cfg.rendered_path, output)
    _update_run_state(cfg, "2-render", "complete", completed_rendered=len(output))
    return output


def _render_one(
    cfg: Config,
    blueprint: LessonBlueprint,
    scene: SceneBrief,
    prepared: PreparedScene,
    provider: Provider | None,
) -> RenderedScene:
    work = cfg.run_dir / "work" / scene.id
    media_dir = cfg.run_dir / "media"
    interactive_dir = cfg.run_dir / "interactive"
    work.mkdir(parents=True, exist_ok=True)
    media_dir.mkdir(parents=True, exist_ok=True)
    # The renderer owns the presentation template; planning style metadata is
    # intentionally ignored at this boundary.
    style = blueprint.style.model_copy(update={"layout": LayoutSpec()})
    narration_seconds = prepared.narration_seconds
    audio = (cfg.run_dir / prepared.narration_path) if prepared.narration_path else None
    if audio is not None and not audio.is_file():
        audio = None

    if prepared.scene_type == SceneType.IMAGE:
        source = cfg.run_dir / str(prepared.asset_path)
        out = media_dir / f"{scene.id}.png"
        concept_image = prepared.debug.get("image_render_mode") == "concept_image"
        if concept_image:
            image_adapter.compose_concept_image(
                source, out, style, brief=scene,
                caption=prepared.caption or image_adapter.caption_for(scene),
            )
        else:
            image_adapter.compose_final(
                source, out, style, title=scene.title, caption=prepared.caption or image_adapter.caption_for(scene),
                brief=scene,
            )
        result = RenderedScene(
            scene_id=scene.id, scene_type=SceneType.IMAGE,
            src=f"media/{scene.id}.png",
            render_mode="concept-image" if concept_image else "api-image+local-compose",
        )
        return _attach_still_audio(cfg, result, scene, audio, narration_seconds, default_seconds=8.0)

    if prepared.scene_type == SceneType.MANIM:
        spec_path = cfg.run_dir / str(prepared.spec_path)
        data = json.loads(spec_path.read_text(encoding="utf-8"))
        body = str(data["construct_body"])
        class_name = str(data.get("scene_class_name") or "EduScene")
        silent = work / f"{scene.id}_silent.mp4"
        mode, guard, final_body, durable = _render_manim_checkpoint(
            cfg, scene, blueprint, work, silent, body, class_name, provider
        )
        if final_body != body:
            # Always keep what actually rendered, for repro; only promote it into the
            # spec when it is a genuine fix. A plain-text downgrade would otherwise
            # burn the LaTeX source into the run and no later re-render could undo it.
            (work / f"{scene.id}_rendered_body.py").write_text(final_body, encoding="utf-8")
            if durable:
                data["construct_body"] = final_body
                spec_path.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
                )
        if data.get("generation_fallback"):
            guard.findings.append(GuardFinding(
                kind="render_fallback", severity="blocker",
                message="the model's Manim code was rejected before rendering; a placeholder scene "
                        "was rendered instead. Reason: " + str(data["generation_fallback"])[:300],
            ))
        out = media_dir / f"{scene.id}.mp4"
        return _finish_video(cfg, scene, silent, out, audio, narration_seconds, mode, guard,
                             debug={"work_dir": str(work)})

    if prepared.scene_type == SceneType.REMOTION:
        spec = remotion_adapter.RemotionSpec.model_validate_json(
            (cfg.run_dir / str(prepared.spec_path)).read_text(encoding="utf-8")
        )
        silent = work / f"{scene.id}_silent.mp4"
        duration = max(narration_seconds or 0.0, scene.target_seconds or 8.0)
        template = cfg.repo_root / "remotion_template"
        mode = "remotion"
        guard = GuardReport(source="remotion")
        try:
            if not template.is_dir() or not shutil.which("npx"):
                raise RuntimeError("Node/Remotion unavailable")
            order = [item.id for item in blueprint.scenes]
            remotion_adapter.render_with_remotion(
                template, work, scene, style, spec, silent, duration,
                scene_index=order.index(scene.id) + 1 if scene.id in order else 0,
                scene_total=len(order),
            )
        except Exception as exc:
            mode = "ffmpeg-slide-fallback"
            (work / "remotion_fallback.txt").write_text(str(exc), encoding="utf-8")
            remotion_adapter.render_fallback_slide(scene, style, spec, work, silent, duration)
            guard.findings.append(GuardFinding(
                kind="render_fallback", severity="minor",
                message="Remotion unavailable; static slide fallback was used",
            ))
        out = media_dir / f"{scene.id}.mp4"
        return _finish_video(
            cfg, scene, silent, out, audio, narration_seconds, mode, guard,
            add_character=mode == "ffmpeg-slide-fallback" and spec.beat != "title_card",
        )

    if prepared.scene_type == SceneType.INTERACTIVE:
        params = InteractiveParams(
            template=prepared.template or scene.template or "multiple_choice",
            parameters=prepared.parameters,
            success_condition=prepared.success_condition,
            instruction=prepared.instruction,
            normalization_warnings=list(prepared.debug.get("normalization_warnings", [])),
            # Interactive panels are rendered by the trusted runtime as a
            # standalone practice surface; regular media scenes use the board.
            teaching_layout={},
        )
        config = interactive_dir / f"{scene.id}.json"
        interactive_adapter.write_interactive_json(params, config)
        preview = work / f"{scene.id}_preview.html"
        interactive_adapter.render_preview_html(params, style, preview)
        result = RenderedScene(
            scene_id=scene.id, scene_type=SceneType.INTERACTIVE,
            src=f"interactive/{scene.id}.json", template=params.template,
            parameters=params.parameters, render_mode="trusted-template-runtime",
            debug={"preview_html": f"work/{scene.id}/{preview.name}"},
        )
        if params.normalization_warnings:
            result.guard.findings.append(GuardFinding(
                kind="render_fallback", severity="major",
                message="generated parameters were invalid; template defaults were restored: "
                        + params.normalization_warnings[0][:200],
            ))
        return _attach_still_audio(cfg, result, scene, audio, narration_seconds, default_seconds=None)
    raise ValueError(f"Unknown prepared type: {prepared.scene_type}")


def _retry_on_guard_blockers(
    cfg: Config,
    blueprint: LessonBlueprint,
    scene: SceneBrief,
    prepared: PreparedScene,
    result: RenderedScene,
    provider: Provider | None,
) -> RenderedScene:
    """One regeneration when the layout guard measured a hard defect.

    The guard's findings are measurements, not opinions, so acting on them needs
    no visual review — and a cut-off or overlapping label is exactly the thing a
    second attempt fixes cheaply.
    """
    if provider is None or scene.scene_type != SceneType.MANIM:
        return result
    # Major layout findings are still visible defects (for example a label can
    # be 45% covered while remaining below the guard's blocker threshold). Treat
    # them as retryable as well; otherwise the render loop ships known overlap.
    blockers = [
        f for f in result.guard.findings
        # `annotation_crowded` is what the annotate helper now reports when no
        # position was fully clear. It used to raise and take the whole scene
        # down; the retry it implicitly forced is worth keeping, the crash is not.
        if f.kind in ("text_overlap", "text_out_of_frame", "text_occluded", "annotation_crowded")
        and f.severity in {"blocker", "major"}
    ]
    if not blockers or prepared.debug.get("guard_retry"):
        return result
    lines = [f"- {f.message}" for f in blockers]
    _log(scene.id, f"layout guard blocked ({len(blockers)}); regenerating once")
    # The retry re-renders to the same media/<id>.mp4 the first attempt wrote, so
    # keep that file aside first. When the rewrite is rejected below we return the
    # first RenderedScene, and the video on disk has to be the render it actually
    # describes -- otherwise the checkpoint's guard report and visual_seconds
    # belong to a frame nobody will ever see, and the restored spec marks the
    # scene current so no later pass re-renders it.
    kept = _keep_render_artifacts(cfg, scene, result)
    try:
        spec_path = cfg.run_dir / str(prepared.spec_path)
        data = json.loads(spec_path.read_text(encoding="utf-8"))
        fixed = manim_adapter.generate_construct(
            provider, scene, blueprint.style,
            prior_body=data["construct_body"],
            guard_lines=[f.message for f in blockers],
            narration_seconds=prepared.narration_seconds,
        )
        before = json.dumps(data, indent=2, ensure_ascii=False)
        data["construct_body"] = fixed.construct_body
        data["scene_class_name"] = fixed.scene_class_name
        spec_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        prepared.debug["guard_retry"] = lines
        retried = _render_one(cfg, blueprint, scene, prepared, provider)
        if _guard_defect_score(retried.guard) < _guard_defect_score(result.guard):
            retried.debug["guard_retry"] = lines
            _drop_kept_artifacts(kept)
            return retried
        # Keeping the first render means keeping the first *body*: leaving the
        # rejected rewrite in the spec would leave the run describing code that
        # never produced the mp4 sitting next to it.
        spec_path.write_text(before, encoding="utf-8")
        _log(scene.id, "regeneration did not clear the guard; keeping the first render")
    except Exception as exc:
        _log(scene.id, f"guard retry failed: {exc}")
    _restore_kept_artifacts(kept)
    return result


def _keep_render_artifacts(
    cfg: Config, scene: SceneBrief, result: RenderedScene
) -> list[tuple[Path, Path]]:
    """Copy the files a re-render would overwrite, so a rejected retry can be undone."""
    kept: list[tuple[Path, Path]] = []
    candidates = [cfg.run_dir / "work" / scene.id / f"{scene.id}_silent.mp4"]
    if result.src:
        candidates.append(cfg.run_dir / result.src)
    for produced in candidates:
        if not produced.is_file():
            continue
        keep = produced.with_name(f"{produced.stem}.pre_guard_retry{produced.suffix}")
        try:
            shutil.copy2(produced, keep)
        except OSError:
            continue
        kept.append((keep, produced))
    return kept


def _restore_kept_artifacts(kept: list[tuple[Path, Path]]) -> None:
    for keep, produced in kept:
        try:
            keep.replace(produced)
        except OSError:
            pass


def _drop_kept_artifacts(kept: list[tuple[Path, Path]]) -> None:
    for keep, _ in kept:
        keep.unlink(missing_ok=True)


def _guard_defect_score(guard: GuardReport) -> int:
    """Rank layout defects so a retry with less overlap can replace the first.

    Finding counts alone miss meaningful improvements such as reducing one
    label's occlusion from 68% to 45%. Percentages are emitted by the Manim
    guard in the finding message; include them in the score when available.
    """
    score = 0
    for finding in guard.findings:
        if finding.kind not in {"text_overlap", "text_out_of_frame", "text_occluded"}:
            continue
        severity = {"blocker": 1000, "major": 500}.get(finding.severity, 0)
        match = re.search(r"(\d+)\s*(?:%|percent)", finding.message)
        area = int(match.group(1)) if match else 100
        score += severity + area
    return score


def _attach_still_audio(
    cfg: Config,
    result: RenderedScene,
    scene: SceneBrief,
    audio: Path | None,
    narration_seconds: float | None,
    *,
    default_seconds: float | None,
) -> RenderedScene:
    if audio is not None:
        dst = cfg.run_dir / "media" / f"{scene.id}.mp3"
        shutil.copy2(audio, dst)
        result.audio_src = f"media/{scene.id}.mp3"
        result.narration_seconds = narration_seconds
    if default_seconds is not None:
        target = scene.target_seconds or default_seconds
        result.visual_seconds = target
        result.duration = max(target, (narration_seconds or 0.0) + 0.8)
    return result


def _finish_video(
    cfg: Config,
    scene: SceneBrief,
    silent: Path,
    out: Path,
    audio: Path | None,
    narration_seconds: float | None,
    mode: str,
    guard: GuardReport,
    debug: dict | None = None,
    add_character: bool = False,
) -> RenderedScene:
    if add_character:
        _overlay_character_video(cfg, scene.id, silent)
    media.ensure_web_playable(silent)
    visual_seconds = media.probe_duration(silent)
    if audio is not None:
        duration = media.mux_narration(silent, audio, out)
        audio_src = f"media/{scene.id}.mp4"  # narration is embedded
    else:
        shutil.copy2(silent, out)
        duration = visual_seconds
        audio_src = None
    if visual_seconds and narration_seconds:
        if visual_seconds < narration_seconds * 0.5:
            guard.findings.append(GuardFinding(
                kind="duration_mismatch", severity="minor",
                message=f"animation ({visual_seconds:.0f}s) is much shorter than narration "
                        f"({narration_seconds:.0f}s); last frame is held",
            ))
        elif visual_seconds > narration_seconds * 2.5 + 4:
            guard.findings.append(GuardFinding(
                kind="duration_mismatch", severity="minor",
                message=f"animation ({visual_seconds:.0f}s) is far longer than narration "
                        f"({narration_seconds:.0f}s)",
            ))
    return RenderedScene(
        scene_id=scene.id, scene_type=scene.scene_type, src=f"media/{scene.id}.mp4",
        duration=duration or scene.target_seconds, visual_seconds=visual_seconds,
        audio_src=audio_src, narration_seconds=narration_seconds,
        render_mode=mode, guard=guard, debug=debug or {},
    )


def _overlay_character_video(cfg: Config, scene_id: str, video: Path) -> None:
    """Add the fixed lower-right homepage character to a local video."""
    character = character_asset_path(scene_id)
    if not character.is_file() or not video.is_file():
        return
    style = _style_for(cfg)
    height = max(1, round(style.layout.height / 6))
    pad = style.layout.padding_px
    temp = video.with_name(video.stem + "_character.mp4")
    # `-loop 1` on the PNG is an endless input, and these silent slides carry no
    # audio track, so the only output stream is one the filtergraph will feed
    # forever: `-shortest` has nothing shorter to stop on and the encode runs
    # until the disk fills (seen in the wild: a 225 KB slide grew a 337 MB
    # "overlay" over 84 minutes at 8 cores).  Bound the looped input explicitly.
    seconds = media.probe_duration(video)
    if not seconds or seconds <= 0:
        return
    try:
        subprocess.run([
            media.ffmpeg_bin(), "-y", "-i", str(video),
            "-loop", "1", "-t", f"{seconds:.3f}", "-i", str(character),
            "-filter_complex",
            f"[1:v]scale=-1:{height}[character];"
            f"[0:v][character]overlay=main_w-overlay_w-{pad}:main_h-overlay_h-{pad}:format=auto[outv]",
            "-map", "[outv]", "-map", "0:a?", "-c:v", "libx264", "-preset", "fast",
            "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "copy",
            "-t", f"{seconds:.3f}", "-shortest", str(temp),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=900)
        temp.replace(video)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        # The character is decoration; a scene without it still teaches.
        pass
    finally:
        temp.unlink(missing_ok=True)


def _render_manim_checkpoint(
    cfg: Config,
    scene: SceneBrief,
    blueprint: LessonBlueprint,
    work: Path,
    out: Path,
    body: str,
    class_name: str,
    provider: Provider | None,
) -> tuple[str, GuardReport, str, bool]:
    """Try the generated body, then (optionally) an API traceback repair, then the
    no-LaTeX rewrite, then the safe fallback.

    Returns (mode, guard, body_used, durable). `durable` is False whenever the body
    that won is a lossy downgrade of the original -- the plain-text rewrite loses the
    LaTeX source, and a body that only renders because the local TeX install is
    missing must never be written back over the spec. Attempts are
    (body, mode, lossy) triples so that flag survives the insert-in-the-middle
    escalation below.
    """
    attempts: list[tuple[str, str, bool]] = [(body, "manim", False)]
    if not manim_adapter.latex_available():
        try:
            attempts.append(
                (manim_adapter.demathify_construct_body(body), "manim-no-latex", True)
            )
        except Exception as exc:
            (work / f"{scene.id}_demath_error.txt").write_text(str(exc), encoding="utf-8")
    work = work.resolve()
    log_path = work / f"{scene.id}_manim.log"
    if log_path.exists():
        log_path.unlink()
    (work / "guard.json").unlink(missing_ok=True)
    last_error = ""
    repaired_once = False
    index = 0
    while index < len(attempts):
        candidate, mode, lossy = attempts[index]
        index += 1
        process, isolation = _run_manim(cfg, scene, blueprint, work, candidate, class_name)
        with log_path.open("a", encoding="utf-8") as log:
            log.write(
                f"\n===== attempt mode={mode} isolation={isolation} rc={process.returncode} =====\n"
                f"{process.stdout}\n{process.stderr}\n"
            )
        if process.returncode == 0:
            produced = manim_adapter._find_mp4(work, scene.id)
            if produced:
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(produced, out)
                guard = manim_adapter.parse_guard_report(work)
                if guard.source.endswith(":missing"):
                    guard.findings.append(GuardFinding(
                        kind="guard_unreadable", severity="blocker",
                        message="the Manim layout guard produced no guard.json; scene geometry is unchecked",
                    ))
                return mode, guard, candidate, not lossy
        last_error = (process.stderr or process.stdout or "")[-2500:]
        (work / "guard.json").unlink(missing_ok=True)
        # A TeX failure means this formula is bad, not the toolchain: retry the
        # scene with the formulas rewritten as plain Unicode. Costs no API call.
        if (any(token in last_error.lower() for token in ("latex", "dvi", ".tex"))
                and not any(m.endswith("no-latex") for _, m, _ in attempts)):
            try:
                attempts.insert(index, (manim_adapter.demathify_construct_body(candidate),
                                        f"{mode}-no-latex", True))
                _log(scene.id, "LaTeX failed; retrying with plain-text formulas")
            except Exception as exc:
                _log(scene.id, f"demathify unavailable: {exc}")
        if provider is not None and not repaired_once and mode in {"manim", "manim-no-latex"}:
            repaired_once = True
            try:
                fixed = manim_adapter.repair_from_stderr(provider, candidate, last_error)
                attempts.insert(index, (fixed, f"{mode}+api-repair", lossy))
                _log(scene.id, "manim failed; applied one traceback repair")
            except Exception as exc:
                _log(scene.id, f"manim traceback repair unavailable: {exc}")
    # Safe fallback: renders *something* so the reviewer can fail it with a clear reason.
    process, _ = _run_manim(cfg, scene, blueprint, work, manim_adapter.FALLBACK_BODY, "EduScene")
    produced = manim_adapter._find_mp4(work, scene.id) if process.returncode == 0 else None
    if produced is None:
        raise RuntimeError(f"Manim render failed: {last_error[-800:]}")
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(produced, out)
    (work / "render_error.txt").write_text(last_error, encoding="utf-8")
    guard = GuardReport(source="manim-layout-guard")
    guard.findings.append(GuardFinding(
        kind="render_fallback", severity="blocker",
        message="generated Manim code crashed; a placeholder scene was rendered instead. "
                "Traceback tail: " + last_error[-600:].strip().replace("\n", " | "),
    ))
    return "manim-safe-fallback", guard, body, False


def _run_manim(cfg, scene, blueprint, work: Path, body: str, class_name: str):
    order = [s.id for s in blueprint.scenes]
    style = blueprint.style.model_copy(update={"layout": LayoutSpec()})
    script = manim_adapter.assemble_script(
        body, style, class_name,
        scene_label=scene.title,
        scene_index=order.index(scene.id) + 1 if scene.id in order else 0,
        scene_total=len(order),
    )
    py_path = work / f"{scene.id}.py"
    py_path.write_text(script, encoding="utf-8")
    cls = manim_adapter._safe_class_name(class_name)
    for stale in work.rglob(f"{scene.id}.mp4"):
        stale.unlink(missing_ok=True)
    cmd = [
        manim_adapter.manim_bin() or "manim",
        f"-q{cfg.manim_quality}", "--format", "mp4", "--disable_caching",
        "-o", f"{scene.id}.mp4", "--media_dir", "media", py_path.name, cls,
    ]
    return manim_adapter._run_restricted(
        cmd, work, timeout=cfg.manim_timeout, container_image=cfg.manim_container_image
    )


# --------------------------------------------------------------------------- review
def review_all(
    cfg: Config,
    provider: Provider,
    blueprint: LessonBlueprint,
    rendered: list[RenderedScene] | None = None,
    *,
    only_scene_ids: set[str] | None = None,
) -> list[RenderedScene]:
    """Audit actual local outputs; a reviewer outage is retried once and never
    silently passes a scene."""
    _update_run_state(cfg, "2-review", "running")
    rendered = rendered or load_rendered(cfg)
    scenes = {scene.id: scene for scene in blueprint.scenes}
    prepared_by_id = {
        item.scene_id: item
        for item in (load_prepared(cfg) if has_prepared_checkpoint(cfg) else [])
    }

    def work(result: RenderedScene) -> RenderedScene:
        if only_scene_ids is not None and result.scene_id not in only_scene_ids:
            _write_scene_checkpoint(cfg, "rendered", result, stage="2-review")
            return result
        scene = scenes.get(result.scene_id)
        if scene is None:
            _write_scene_checkpoint(cfg, "rendered", result, stage="2-review")
            return result
        reviewed = _review_one(cfg, provider, blueprint, scene, result, prepared_by_id.get(scene.id))
        _write_scene_checkpoint(cfg, "rendered", reviewed, stage="2-review")
        return reviewed

    targets = [r for r in rendered]
    workers = max(1, min(cfg.parallel, len(targets) or 1))
    if workers == 1:
        reviewed = [work(r) for r in targets]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            reviewed = list(pool.map(work, targets))
    _write_models(cfg.rendered_path, reviewed)
    _update_run_state(cfg, "2-review", "complete", reviewed=len(reviewed))
    return reviewed


def _review_one(
    cfg: Config,
    provider: Provider,
    blueprint: LessonBlueprint,
    scene: SceneBrief,
    result: RenderedScene,
    prepared: PreparedScene | None,
) -> RenderedScene:
    attempt = int(result.debug.get("prepared_attempt", 0) or 0)
    if not result.src:
        # Render failure: needs a fresh preparation, not a review retry.
        result.repair = SceneRepair(
            scene_id=scene.id, scene_type=scene.scene_type, passed=False, score=0.0,
            severity="blocker", fix_action="re_render",
            blocking_issues=[f"Render failed: {result.review_notes or 'unknown error'}"],
        ).finalize()
        result.review_passed = False
        result.review_error = False
        result.review_notes = result.repair.summary_text()
        reviewer.dump_review(cfg.run_dir / "debug" / f"{scene.id}_review_r{attempt}.json",
                             result.repair, [], result.guard)
        return result

    frames, extra = preview_frames(cfg, result, scene)
    guard = result.guard.model_copy(deep=True)
    # Review-time findings are recomputed from the frames on every pass, so drop the
    # previous pass's copies first. They used to be inherited, which meant a scene
    # that had once rendered blank kept failing on that finding after it was fixed —
    # and the reviewer, reading it in the prompt, dutifully repeated the complaint.
    guard.findings = [f for f in guard.findings if f.kind not in REVIEW_TIME_GUARD_KINDS]
    for finding in extra:
        guard.findings.append(finding)
    if result.scene_type in (SceneType.MANIM, SceneType.REMOTION):
        for finding in media.blank_frame_findings(frames):
            guard.findings.append(finding)
    result.guard = guard
    artifact = repair_router.load_artifact_excerpt(cfg.run_dir, prepared)

    repair: SceneRepair | None = None
    for round_ in range(2):
        repair = reviewer.review_scene(
            provider, blueprint.style, frames, scene=scene, guard=guard,
            artifact_excerpt=artifact, pass_score=cfg.review_pass_score,
            visual_seconds=result.visual_seconds, narration_seconds=result.narration_seconds,
            opener=bool(blueprint.scenes) and scene.id == blueprint.scenes[0].id,
        )
        if not repair.review_error:
            break
        _log(scene.id, f"review error ({repair.blocking_issues[:1]}); retrying")
        time.sleep(2.0)
    assert repair is not None
    result.repair = repair
    result.review_passed = repair.passed
    result.review_error = bool(repair.review_error)
    result.review_notes = repair.summary_text()
    result.debug["review_attempt"] = attempt
    result.debug["frames"] = [str(f.path.relative_to(cfg.run_dir)) for f in frames]
    reviewer.dump_review(cfg.run_dir / "debug" / f"{scene.id}_review_r{attempt}.json",
                         repair, frames, guard)
    status = "PASS" if repair.passed else ("REVIEW-ERROR" if repair.review_error else "FAIL")
    _log(scene.id, f"review {status} score={repair.score} adherence={repair.brief_adherence}"
                   + (f" blocking={len(repair.blocking_issues)}" if repair.blocking_issues else ""))
    return result


# Guard kinds produced while reviewing (from the sampled frames, or from the
# prior artifact), not while rendering. They are rebuilt on every review pass, so
# a stale copy must not survive into the next one.
REVIEW_TIME_GUARD_KINDS = frozenset({
    "blank_frame", "dom_overflow", "missing_asset", "grid_anchor_overlap",
})


def preview_frames(
    cfg: Config, rendered: RenderedScene, scene: SceneBrief
) -> tuple[list[media.Frame], list[GuardFinding]]:
    frames_dir = cfg.run_dir / "frames"
    if rendered.scene_type in (SceneType.MANIM, SceneType.REMOTION):
        video = cfg.run_dir / rendered.src
        if not video.is_file():
            return [], [GuardFinding(kind="missing_asset", severity="blocker",
                                     message=f"video missing: {rendered.src}")]
        sample_count = cfg.frames_per_video + (2 if rendered.scene_type == SceneType.REMOTION else 0)
        duration = rendered.visual_seconds or media.probe_duration(video) or 0.0
        extra = rendered.guard.flagged_seconds()
        # Remotion has no runtime layout guard; include the first and last
        # composited frames so reveal/fade transitions are represented in QA.
        if rendered.scene_type == SceneType.REMOTION and duration > 0:
            extra = [0.0, max(0.0, duration - 0.05), *extra]
        frames = media.extract_video_frames(
            video, frames_dir, scene.id, count=sample_count,
            extra_seconds=extra, max_width=cfg.frame_width,
        )
        return frames, []
    if rendered.scene_type == SceneType.IMAGE:
        image = cfg.run_dir / rendered.src
        if not image.is_file():
            return [], [GuardFinding(kind="missing_asset", severity="blocker",
                                     message=f"image missing: {rendered.src}")]
        return [media.Frame(path=image, seconds=0.0, label="still")], []
    if rendered.scene_type == SceneType.INTERACTIVE:
        raw = str(rendered.debug.get("preview_html", "") or "")
        html = Path(raw)
        if not html.is_file():
            html = (cfg.run_dir / raw).resolve() if raw else html
        if not html.is_file():
            candidate = cfg.run_dir / "work" / scene.id / f"{scene.id}_preview.html"
            if candidate.is_file():
                html = candidate
        if not html.is_file():
            return [], [GuardFinding(kind="missing_asset", severity="blocker",
                                     message="interactive preview html missing")]
        shot = frames_dir / f"{scene.id}_interactive.png"
        style = _style_for(cfg)
        captured, findings = reviewer.screenshot_html(
            html, shot, width=style.layout.width, height=style.layout.height
        )
        frames = [media.Frame(path=captured, seconds=0.0, label="screenshot")] if captured else []
        return frames, findings
    return [], []


def _style_for(cfg: Config):
    from ..schema import StyleConfig

    try:
        return StyleConfig.model_validate_json(cfg.style_path.read_text(encoding="utf-8"))
    except Exception:
        return StyleConfig()


# --------------------------------------------------------------------------- one-machine loop
def run_repair_loop(cfg: Config, provider: Provider, blueprint: LessonBlueprint) -> list[RenderedScene]:
    """prepare → render → review, re-doing only failed scenes, up to max_review_rounds reviews."""
    prepared: list[PreparedScene] = []
    rendered: list[RenderedScene] = []
    targets: set[str] = {scene.id for scene in blueprint.scenes}
    repairs: dict[str, SceneRepair] = {}
    rounds = max(1, cfg.max_review_rounds)
    start_round = 0
    if has_prepared_checkpoint(cfg) and has_rendered_checkpoint(cfg):
        # Resume: keep every passed scene, re-do only the failures (within their budget).
        prepared = load_prepared(cfg)
        rendered = load_rendered(cfg)
        stale_prepared = stale_prepared_scene_ids(cfg, blueprint, prepared)
        stale_rendered = stale_rendered_scene_ids(cfg, blueprint, prepared, rendered)
        current_prepared = {p.scene_id for p in prepared} - stale_prepared
        current_rendered = {r.scene_id for r in rendered} - stale_rendered
        known = current_prepared & current_rendered
        attempts = {p.scene_id: p.attempt for p in prepared}
        failed = [
            r for r in rendered
            if r.scene_id in known and not r.review_passed and not r.review_error
            and (r.repair is None or r.repair.needs_repair())
        ]
        stale = {scene.id for scene in blueprint.scenes if scene.id not in known}
        targets = stale | {r.scene_id for r in failed if attempts.get(r.scene_id, 0) < rounds - 1}
        exhausted = {r.scene_id for r in failed if attempts.get(r.scene_id, 0) >= rounds - 1}
        repairs = repair_router.repairs_from_rendered(
            [r for r in failed if r.scene_id in targets], include_review_errors=False
        )
        for scene_id in stale:
            repairs.pop(scene_id, None)
        if exhausted:
            print(f"  Stage 2 resume: budget exhausted for {sorted(exhausted)} (see debug/*_HITL.txt)", flush=True)
        if not targets:
            print("  Stage 2 resume: nothing left to repair.", flush=True)
            return rendered
        start_round = min(rounds - 1, max(attempts.get(t, 0) for t in targets) + (1 if repairs else 0))
        print(f"  Stage 2 resume: re-doing {sorted(targets)}", flush=True)
    for rnd in range(start_round, rounds):
        print(f"  Stage 2 round {rnd + 1}/{rounds}: {sorted(targets)}", flush=True)
        prepared = prepare_all(
            cfg, provider, blueprint, previous=prepared, only_scene_ids=targets, repairs_by_id=repairs
        )
        rendered = render_all(
            cfg, blueprint, prepared, previous=rendered, only_scene_ids=targets, provider=provider
        )
        rendered = review_all(cfg, provider, blueprint, rendered, only_scene_ids=targets)
        targets = {
            item.scene_id
            for item in rendered
            if not item.review_passed
            and not item.review_error
            and (item.repair is None or item.repair.needs_repair())
        }
        if not targets or rnd == rounds - 1:
            break
        repairs = repair_router.repairs_from_rendered(
            [item for item in rendered if item.scene_id in targets], include_review_errors=False
        )
        _apply_tool_changes(cfg, blueprint, repairs)
    for item in rendered:
        if item.review_error:
            write_hitl(cfg, item, "Reviewer unavailable; scene could not be audited.")
        elif not item.review_passed:
            write_hitl(cfg, item, f"Review did not pass after {rounds} rounds.")
    return rendered


def _apply_tool_changes(cfg: Config, blueprint: LessonBlueprint, repairs: dict[str, SceneRepair]) -> None:
    """Honour `change_tool`: a typographic Remotion beat or a still image cannot show a
    diagram, so the scene is re-routed to Manim (when enabled) and the blueprint saved."""
    if not cfg.request.enable_manim:
        return
    changed = False
    for scene in blueprint.scenes:
        repair = repairs.get(scene.id)
        if repair is None or repair.fix_action != "change_tool":
            continue
        if scene.scene_type in (SceneType.REMOTION, SceneType.IMAGE):
            _log(scene.id, f"reviewer asked to change tool: {scene.scene_type.value} → manim")
            scene.scene_type = SceneType.MANIM
            scene.rationale = (scene.rationale or "") + " [re-routed to manim by reviewer]"
            repair.fix_action = "re_render"
            repair.scene_type = SceneType.MANIM
            changed = True
    if changed:
        cfg.blueprint_path.write_text(blueprint.model_dump_json(indent=2), encoding="utf-8")


def _render_error(scene: SceneBrief, message: str, attempt: int = 0) -> RenderedScene:
    return RenderedScene(
        scene_id=scene.id, scene_type=scene.scene_type, src="",
        review_passed=False, review_error=False, review_notes=message,
        render_mode="failed", debug={"prepared_attempt": attempt},
    )
