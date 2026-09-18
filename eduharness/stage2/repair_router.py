"""Route SceneRepair onto prior tool artifacts (patch-first, regen fallback)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..providers.base import Provider
from ..schema import (
    InteractiveParams,
    PreparedScene,
    SceneBrief,
    SceneRepair,
    SceneType,
    StyleConfig,
    SuccessCondition,
)
from .adapters import image as image_adapter
from .adapters import interactive as interactive_adapter
from .adapters import manim as manim_adapter
from .adapters import remotion as remotion_adapter
from .repair_apply import (
    apply_interactive_ops,
    apply_manim_ops,
    apply_remotion_ops,
    prompt_addendum_from_ops,
)
from ..templates import registry


def repairs_from_rendered(rendered: list, *, include_review_errors: bool = True) -> dict[str, SceneRepair]:
    """Build repairs_by_id from failed RenderedScene entries."""
    out: dict[str, SceneRepair] = {}
    for item in rendered:
        if getattr(item, "review_passed", False):
            continue
        if not include_review_errors and getattr(item, "review_error", False):
            continue
        repair = getattr(item, "repair", None)
        if repair is None:
            repair = SceneRepair(
                scene_id=item.scene_id,
                scene_type=item.scene_type,
                passed=False,
                score=0.0,
                severity="major",
                fix_action="re_render",
                blocking_issues=[getattr(item, "review_notes", "") or "Scene did not pass"],
            ).finalize()
        else:
            repair = repair.model_copy(
                update={
                    "scene_id": repair.scene_id or item.scene_id,
                    "scene_type": repair.scene_type or item.scene_type,
                }
            )
        if repair.needs_repair():
            out[item.scene_id] = repair
    return out


def _may_patch(prior: PreparedScene | None, repair: SceneRepair | None) -> bool:
    """Patch only once per artifact: if the last round already patched it and the
    scene still failed, the defect is structural and needs a full regeneration.

    Pure placement ops are the exception. Moving an object to different anchors
    cannot break what the scene draws, and layout usually settles over two passes
    (the second collision is often only visible once the first one is gone), so
    those keep their patch route instead of forcing a rewrite of the whole scene.
    """
    if repair is None or repair.fix_action != "patch_artifact" or not repair.ops:
        return False
    if prior is not None and prior.debug.get("repair_mode") in {"patched", "partial_patch", "generation_fallback"}:
        placements_only = (
            prior.scene_type == SceneType.MANIM
            and all((op.target or "").strip() not in {"construct_body", "body"} for op in repair.ops)
        )
        return placements_only
    return True


def prepare_with_repair(
    *,
    provider: Provider,
    scene: SceneBrief,
    style: StyleConfig,
    work: Path,
    run_dir: Path,
    prior: PreparedScene | None,
    repair: SceneRepair | None,
    attempt: int,
    narration_seconds: float | None = None,
    image_prompt_model: str = "gpt-4o",
    audience: str = "general learners",
    language: str = "English",
    opener: bool = False,
) -> PreparedScene:
    """Prepare one scene, applying structured repair ops when possible.

    ``opener`` marks the lesson's first scene, which is pinned to the title card.
    """
    feedback = repair.feedback_text() if repair else ""
    if repair and not repair.needs_repair() and prior is not None:
        return prior.model_copy(update={"attempt": attempt, "repair": repair, "feedback": feedback})

    if scene.scene_type == SceneType.IMAGE:
        return _prepare_image(provider, scene, style, work, run_dir, repair, feedback, attempt,
                              image_prompt_model=image_prompt_model, audience=audience, language=language)
    if scene.scene_type == SceneType.MANIM:
        return _prepare_manim(
            provider, scene, style, work, run_dir, prior, repair, feedback, attempt, narration_seconds
        )
    if scene.scene_type == SceneType.REMOTION:
        return _prepare_remotion(
            provider, scene, style, work, run_dir, prior, repair, feedback, attempt,
            narration_seconds, opener=opener,
        )
    if scene.scene_type == SceneType.INTERACTIVE:
        return _prepare_interactive(
            provider, scene, style, work, run_dir, prior, repair, feedback, attempt
        )
    raise ValueError(f"Unknown scene type: {scene.scene_type}")


def _prepare_image(
    provider: Provider,
    scene: SceneBrief,
    style: StyleConfig,
    work: Path,
    run_dir: Path,
    repair: SceneRepair | None,
    feedback: str,
    attempt: int,
    *,
    image_prompt_model: str = "gpt-4o",
    audience: str = "general learners",
    language: str = "English",
) -> PreparedScene:
    prompt = image_adapter.generate_prompt(
        provider, scene, style, repair=repair, feedback=feedback,
        model=image_prompt_model, audience=audience, language=language,
    )
    source = work / "prepared_source.png"
    (work / "image_prompt.txt").write_text(prompt, encoding="utf-8")
    provider.image(prompt, str(source), size="1536x1024")
    debug: dict[str, Any] = {"prompt": prompt, "image_render_mode": "concept_image",
                             "image_prompt_model": image_prompt_model}
    if repair and repair.ops:
        addendum = prompt_addendum_from_ops(repair.ops)
        if addendum:
            debug["prompt_addendum"] = addendum
            debug["repair_mode"] = "patched"
    elif repair:
        debug["repair_mode"] = "re_render"
    return PreparedScene(
        scene_id=scene.id,
        scene_type=scene.scene_type,
        asset_path=str(source.relative_to(run_dir)),
        caption=image_adapter.caption_for(scene),
        feedback=feedback,
        repair=repair,
        attempt=attempt,
        debug=debug,
    )


def _prepare_manim(
    provider: Provider,
    scene: SceneBrief,
    style: StyleConfig,
    work: Path,
    run_dir: Path,
    prior: PreparedScene | None,
    repair: SceneRepair | None,
    feedback: str,
    attempt: int,
    narration_seconds: float | None,
) -> PreparedScene:
    # A failed API retry should not erase a usable prior Manim artifact. This
    # keeps the render stage productive during transient provider outages while
    # still recording the retry issue for review.
    cached_path = (run_dir / prior.spec_path) if (prior is not None and prior.spec_path) else (work / "manim_spec.json")
    if repair is None and cached_path.is_file():
        if prior is not None and prior.spec_path:
            prior_body, prior_class = _load_manim_prior(run_dir, prior)
        else:
            cached = json.loads(cached_path.read_text(encoding="utf-8"))
            prior_body, prior_class = str(cached.get("construct_body") or ""), str(cached.get("scene_class_name") or "EduScene")
        if prior_body:
            path = work / "manim_spec.json"
            payload = {"construct_body": prior_body, "scene_class_name": prior_class}
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            return prior.model_copy(update={
                "spec_path": str(path.relative_to(run_dir)),
                "attempt": attempt,
                "debug": {k: v for k, v in {**prior.debug, "repair_mode": "prior_reused"}.items() if k != "prepare_error"},
            })
    prior_body, class_name = _load_manim_prior(run_dir, prior)
    mode = "generated"
    body = ""
    applied: list[str] = []
    failed: list[str] = []

    if _may_patch(prior, repair) and prior_body:
        result = apply_manim_ops(prior_body, repair.ops)
        applied, failed = result.applied, result.failed
        if result.ok and isinstance(result.artifact, str):
            body = result.artifact
            mode = "patched"
        elif result.applied and isinstance(result.artifact, str):
            prior_body = result.artifact
            mode = "partial_patch"

    if not body:
        try:
            spec = manim_adapter.generate_construct(
                provider,
                scene,
                style,
                feedback=feedback,
                prior_body=prior_body if repair else "",
                repair_ops=repair.ops if repair else None,
                narration_seconds=narration_seconds,
            )
            body = spec.construct_body
            class_name = spec.scene_class_name
            mode = "targeted_regen" if repair else "generated"
            if spec.fallback_reason:
                mode = "generation_fallback"
        except Exception:
            existing = work / "manim_spec.json"
            if not existing.is_file():
                raise
            cached = json.loads(existing.read_text(encoding="utf-8"))
            body = str(cached.get("construct_body") or "")
            class_name = str(cached.get("scene_class_name") or class_name)
            if not body:
                raise
            mode = "prior_reused"

    path = work / "manim_spec.json"
    payload = {"construct_body": body, "scene_class_name": class_name}
    if mode == "generation_fallback":
        payload["generation_fallback"] = spec.fallback_reason[:600]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return PreparedScene(
        scene_id=scene.id,
        scene_type=scene.scene_type,
        spec_path=str(path.relative_to(run_dir)),
        feedback=feedback,
        repair=repair,
        attempt=attempt,
        debug={
            "manim_class": class_name,
            "repair_mode": mode,
            "ops_applied": applied,
            "ops_failed": failed,
        },
    )


def _prepare_remotion(
    provider: Provider,
    scene: SceneBrief,
    style: StyleConfig,
    work: Path,
    run_dir: Path,
    prior: PreparedScene | None,
    repair: SceneRepair | None,
    feedback: str,
    attempt: int,
    narration_seconds: float | None,
    opener: bool = False,
) -> PreparedScene:
    prior_spec = _load_json_prior(run_dir, prior)
    mode = "generated"
    applied: list[str] = []
    failed: list[str] = []
    data: dict[str, Any] | None = None

    if _may_patch(prior, repair) and prior_spec:
        result = apply_remotion_ops(prior_spec, repair.ops)
        applied, failed = result.applied, result.failed
        if result.ok and isinstance(result.artifact, dict):
            data = remotion_adapter.RemotionSpec.model_validate(result.artifact).model_dump()
            mode = "patched"
        elif result.applied and isinstance(result.artifact, dict):
            prior_spec = result.artifact
            mode = "partial_patch"

    if data is None:
        spec = remotion_adapter.generate_spec(
            provider,
            scene,
            feedback=feedback,
            style=style,
            prior_spec=prior_spec if repair else None,
            repair_ops=repair.ops if repair else None,
            narration_seconds=narration_seconds,
            opener=opener,
        )
        data = spec.model_dump()
        mode = "targeted_regen" if repair else "generated"

    if opener:
        # A repair op can also swap the beat, so pin the opener after every route.
        data = remotion_adapter.as_title_card(
            remotion_adapter.RemotionSpec.model_validate(data)
        ).model_dump()

    path = work / "remotion_spec.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return PreparedScene(
        scene_id=scene.id,
        scene_type=scene.scene_type,
        spec_path=str(path.relative_to(run_dir)),
        feedback=feedback,
        repair=repair,
        attempt=attempt,
        debug={"repair_mode": mode, "ops_applied": applied, "ops_failed": failed,
               "beat": data.get("beat")},
    )


def _prepare_interactive(
    provider: Provider,
    scene: SceneBrief,
    style: StyleConfig,
    work: Path,
    run_dir: Path,
    prior: PreparedScene | None,
    repair: SceneRepair | None,
    feedback: str,
    attempt: int,
) -> PreparedScene:
    prior_payload = _load_json_prior(run_dir, prior)
    mode = "generated"
    applied: list[str] = []
    failed: list[str] = []
    params: InteractiveParams | None = None

    if _may_patch(prior, repair) and prior_payload:
        result = apply_interactive_ops(prior_payload, repair.ops)
        applied, failed = result.applied, result.failed
        if result.ok and isinstance(result.artifact, dict):
            params = _interactive_from_payload(result.artifact, scene)
            mode = "patched"
        elif result.applied and isinstance(result.artifact, dict):
            prior_payload = result.artifact
            mode = "partial_patch"

    if params is None:
        params = interactive_adapter.fill_interactive(
            provider,
            scene,
            style,
            feedback=feedback,
            prior_params=prior_payload if repair else None,
            repair_ops=repair.ops if repair else None,
        )
        mode = "targeted_regen" if repair else "generated"

    path = work / "interactive_spec.json"
    path.write_text(params.model_dump_json(indent=2), encoding="utf-8")
    return PreparedScene(
        scene_id=scene.id,
        scene_type=scene.scene_type,
        spec_path=str(path.relative_to(run_dir)),
        template=params.template,
        parameters=params.parameters,
        success_condition=params.success_condition,
        instruction=params.instruction,
        feedback=feedback,
        repair=repair,
        attempt=attempt,
        debug={
            "normalization_warnings": params.normalization_warnings,
            "repair_mode": mode,
            "ops_applied": applied,
            "ops_failed": failed,
        },
    )


def _interactive_from_payload(payload: dict[str, Any], scene: SceneBrief) -> InteractiveParams:
    tid = str(payload.get("template") or scene.template or "multiple_choice")
    if tid not in registry.list_templates():
        tid = scene.template or "multiple_choice"
        if tid not in registry.list_templates():
            tid = "multiple_choice"
    raw_params = dict(payload.get("parameters") or {})
    params, warnings = registry.normalize_params(tid, raw_params)
    trusted = registry.success_condition_for(tid)
    return InteractiveParams(
        template=tid,
        parameters=params,
        success_condition=SuccessCondition.model_validate(trusted),
        instruction=str(payload.get("instruction") or params.get("instruction") or ""),
        normalization_warnings=warnings,
        teaching_layout=dict(payload.get("teaching_layout") or {}),
    )


def _load_manim_prior(run_dir: Path, prior: PreparedScene | None) -> tuple[str, str]:
    if prior is None or not prior.spec_path:
        return "", "EduScene"
    path = run_dir / prior.spec_path
    if not path.is_file():
        return "", "EduScene"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return str(data.get("construct_body") or ""), str(data.get("scene_class_name") or "EduScene")
    except Exception:
        return "", "EduScene"


def _load_json_prior(run_dir: Path, prior: PreparedScene | None) -> dict[str, Any] | None:
    if prior is None or not prior.spec_path:
        return None
    path = run_dir / prior.spec_path
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def load_artifact_excerpt(run_dir: Path, prepared: PreparedScene | None, limit: int = 6000) -> str:
    """Short prior artifact text for the tool-aware reviewer."""
    if prepared is None or not prepared.spec_path:
        return ""
    path = run_dir / prepared.spec_path
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    if len(text) > limit:
        return text[:limit] + "\n…[truncated]"
    return text
