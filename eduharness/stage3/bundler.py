"""Stage 3 — package EduBundle + generate interactive player HTML."""

from __future__ import annotations

import json
import hashlib
import math
import shutil
from pathlib import Path

from ..schema import (
    InteractiveOverlay,
    LessonBlueprint,
    Manifest,
    RenderedScene,
    SceneType,
    TimelineItem,
)
from .player import write_player


def build_bundle(
    run_dir: Path,
    blueprint: LessonBlueprint,
    rendered: list[RenderedScene],
    bundle_id: str,
    *,
    allow_unreviewed: bool = False,
) -> Manifest:
    # A review override cannot make incomplete media or a broken timeline usable.
    # Validate the whole input before touching an already published bundle.
    by_id, problems = _validate_bundle_inputs(run_dir, blueprint, rendered)
    if problems and not allow_unreviewed:
        raise RuntimeError(
            "Bundle blocked by strict quality gate:\n- " + "\n- ".join(problems)
        )

    bundle = run_dir / "bundle"
    media_dst = bundle / "media"
    inter_dst = bundle / "interactive"
    media_dst.mkdir(parents=True, exist_ok=True)
    inter_dst.mkdir(parents=True, exist_ok=True)

    if problems:
        (bundle / "warnings.json").write_text(
            json.dumps({"problems": problems, "allow_unreviewed": True}, indent=2),
            encoding="utf-8",
        )
    else:
        (bundle / "warnings.json").unlink(missing_ok=True)

    timeline: list[TimelineItem] = []
    timeline_by_id: dict[str, TimelineItem] = {}
    cursor = 0.0

    for scene in blueprint.scenes:
        r = by_id[scene.id]

        audio_src = _copy_standalone_audio(run_dir, media_dst, r)

        if r.scene_type == SceneType.INTERACTIVE:
            src_path = run_dir / r.src
            shutil.copy2(src_path, inter_dst / src_path.name)
            config_src = f"interactive/{Path(r.src).name}"
            if scene.trigger_scene_id:
                target = timeline_by_id[scene.trigger_scene_id]
                target.overlays.append(
                    InteractiveOverlay(
                        id=scene.id,
                        trigger_at=scene.trigger_at_seconds or 0.0,
                        template=r.template or scene.template or "multiple_choice",
                        config_src=config_src,
                        title=scene.title,
                        audio_src=audio_src,
                        narration=scene.narration,
                    )
                )
                continue
            item = TimelineItem(
                id=scene.id,
                type="interactive",
                trigger_at=cursor,
                template=r.template,
                config_src=config_src,
                title=scene.title,
                audio_src=audio_src,
                narration=scene.narration,
            )
            timeline.append(item)
            timeline_by_id[item.id] = item
            # Interactive nodes pause the stream; don't advance cursor duration
            continue

        src_path = run_dir / r.src
        shutil.copy2(src_path, media_dst / src_path.name)

        kind = "image" if r.scene_type == SceneType.IMAGE else "video"
        dur = r.duration or (8.0 if kind == "image" else 10.0)
        item = TimelineItem(
            id=scene.id,
            type=kind,  # type: ignore[arg-type]
            src=f"media/{Path(r.src).name}",
            audio_src=audio_src if kind == "image" else None,
            duration=dur,
            title=scene.title,
            narration=scene.narration,
        )
        timeline.append(item)
        timeline_by_id[item.id] = item
        cursor += dur

    manifest = Manifest(
        bundle_id=bundle_id,
        topic=blueprint.topic,
        style=blueprint.style,
        timeline=timeline,
        total_duration=cursor,
    )
    manifest.content_version = _bundle_content_version(bundle, manifest)
    manifest_json = manifest.model_dump_json(indent=2)
    (bundle / "manifest.json").write_text(manifest_json, encoding="utf-8")
    # Compatibility copy generated from the exact manifest style source.
    (bundle / "style_config.json").write_text(
        manifest.style.model_dump_json(indent=2), encoding="utf-8"
    )
    write_player(bundle, manifest)
    return manifest


def _validate_bundle_inputs(
    run_dir: Path,
    blueprint: LessonBlueprint,
    rendered: list[RenderedScene],
) -> tuple[dict[str, RenderedScene], list[str]]:
    """Fail closed on structural defects; return only review warnings."""
    errors: list[str] = []
    warnings: list[str] = []
    by_id: dict[str, RenderedScene] = {}
    for result in rendered:
        if result.scene_id in by_id:
            errors.append(f"{result.scene_id}: duplicate rendered scene ID")
        by_id[result.scene_id] = result

    if not blueprint.scenes:
        errors.append("blueprint has no scenes")
    scene_ids: set[str] = set()
    prior_videos: dict[str, float] = {}
    for scene in blueprint.scenes:
        if not scene.id:
            errors.append("blueprint scene has no ID")
        if scene.id in scene_ids:
            errors.append(f"{scene.id}: duplicate blueprint scene ID")
        scene_ids.add(scene.id)
        result = by_id.get(scene.id)
        if result is None:
            errors.append(f"{scene.id}: no rendered result")
        else:
            if result.scene_type != scene.scene_type:
                errors.append(
                    f"{scene.id}: rendered scene type {result.scene_type.value!r} "
                    f"does not match blueprint type {scene.scene_type.value!r}"
                )
            if not result.src:
                errors.append(f"{scene.id}: no rendered source")
            elif not (run_dir / result.src).is_file():
                errors.append(f"{scene.id}: source file missing: {result.src}")
            if not result.review_passed:
                warnings.append(f"{scene.id}: visual review did not pass")

        if scene.trigger_scene_id is not None:
            if scene.scene_type != SceneType.INTERACTIVE:
                errors.append(f"{scene.id}: only interactive scenes can have overlay triggers")
            limit = prior_videos.get(scene.trigger_scene_id)
            if limit is None:
                errors.append(
                    f"{scene.id}: overlay target {scene.trigger_scene_id!r} "
                    "must be an earlier video scene"
                )
            trigger = scene.trigger_at_seconds or 0.0
            if not math.isfinite(trigger) or trigger < 0:
                errors.append(f"{scene.id}: trigger_at_seconds must be finite and nonnegative")
            elif limit is not None and trigger >= limit:
                errors.append(
                    f"{scene.id}: trigger_at_seconds {trigger} is outside "
                    f"{scene.trigger_scene_id} duration {limit}"
                )
        elif scene.trigger_at_seconds is not None:
            errors.append(f"{scene.id}: trigger_at_seconds requires an overlay target")

        if result is not None and scene.scene_type != SceneType.INTERACTIVE:
            duration = result.duration if result.duration is not None else (
                8.0 if scene.scene_type == SceneType.IMAGE else 10.0
            )
            if not math.isfinite(duration) or duration <= 0:
                errors.append(f"{scene.id}: duration must be finite and positive")
            elif scene.scene_type in (SceneType.MANIM, SceneType.REMOTION):
                prior_videos[scene.id] = duration

    for scene_id in by_id.keys() - scene_ids:
        errors.append(f"{scene_id}: no blueprint scene")
    if errors:
        raise RuntimeError("Bundle blocked by structural validation:\n- " + "\n- ".join(errors))
    return by_id, warnings


def _bundle_content_version(bundle: Path, manifest: Manifest) -> str:
    """Hash packaged bytes as well as metadata, keeping player resume honest."""
    digest = hashlib.sha256()
    digest.update(manifest.model_dump_json(exclude={"content_version"}).encode("utf-8"))
    for path in sorted((*((bundle / "media").glob("*")), *((bundle / "interactive").glob("*")))):
        if not path.is_file():
            continue
        digest.update(path.relative_to(bundle).as_posix().encode("utf-8"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()[:32]


def _copy_standalone_audio(run_dir: Path, media_dst: Path, r: RenderedScene) -> str | None:
    """Narration for image/interactive scenes ships as a separate mp3 (video has it embedded)."""
    if not r.audio_src or r.audio_src.endswith(".mp4"):
        return None
    src = run_dir / r.audio_src
    if not src.is_file():
        return None
    shutil.copy2(src, media_dst / src.name)
    return f"media/{src.name}"
