"""Dependency-free local UI for inspecting and resuming EduHarness builds.

The studio deliberately invokes the public ``python -m eduharness`` CLI instead
of importing pipeline internals into the HTTP process. Jobs therefore keep the
same checkpoint semantics as command-line runs, while their metadata and logs
survive a browser disconnect.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import mimetypes
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from typing import Any
from urllib.parse import unquote, urlparse
from http import HTTPStatus

from ..config import find_dotenv, load_dotenv
from ..schema import HarnessRequest
from ..serve import RangeHandler, ThreadingHTTPServer, _RANGE

load_dotenv(find_dotenv(usecwd=True))


ASSET_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ASSET_DIR.parents[1]
RUNS_ROOT = PROJECT_ROOT / "runs"
_SAFE_ID = re.compile(r"^[0-9A-Za-z][0-9A-Za-z_-]{0,95}$")
_VALID_STAGES = {"all", "1", "2", "2-prepare", "2-render", "2-review", "3"}
_JOB_LOCK = threading.Lock()
_OPENAI_KEY = re.compile(r"^sk-[A-Za-z0-9_-]{20,}$")


def normalize_user_api_key(value: Any) -> str:
    """Validate a user-supplied OpenAI key without storing or logging it."""
    if not isinstance(value, str):
        raise ValueError("Please enter a valid OpenAI API key.")
    value = value.strip()
    if not value or not _OPENAI_KEY.fullmatch(value):
        raise ValueError("Please enter a valid OpenAI API key.")
    return value


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _iso(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def _latest_mtime(run_dir: Path) -> float:
    candidates = [
        run_dir / "request.json",
        run_dir / "blueprint" / "lesson_blueprint.json",
        run_dir / "prepared_scenes.json",
        run_dir / "rendered_scenes.json",
        run_dir / "bundle" / "manifest.json",
        run_dir / ".studio" / "job.json",
        run_dir / ".studio" / "run_state.json",
        run_dir / ".studio" / "job.log",
    ]
    values = [path.stat().st_mtime for path in candidates if path.is_file()]
    for pattern in (".studio/checkpoints/prepared/*.json", ".studio/checkpoints/rendered/*.json"):
        values.extend(path.stat().st_mtime for path in run_dir.glob(pattern) if path.is_file())
    return max(values, default=run_dir.stat().st_mtime)


def _pid_alive(pid: Any) -> bool:
    try:
        value = int(pid)
        if value <= 0:
            return False
        os.kill(value, 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def _inferred_request(run_id: str, blueprint: dict[str, Any]) -> dict[str, Any]:
    scene_types = {str(scene.get("scene_type", "")) for scene in blueprint.get("scenes", [])}
    return {
        "request_id": run_id,
        "topic": blueprint.get("topic") or run_id.replace("_", " ").replace("-", " ").title(),
        "audience": blueprint.get("audience") or "undergraduate students",
        "learning_goal": blueprint.get("learning_goal") or "",
        "source_text": "",
        "preferred_theme": (blueprint.get("style") or {}).get("theme", "studio_light"),
        "language": "en",
        "max_review_rounds": 3,
        "enable_remotion": "remotion" in scene_types,
        "enable_manim": "manim" in scene_types,
        "enable_image": "image" in scene_types,
        "enable_narration": True,
        "voice": "alloy",
        "allow_unreviewed_bundle": False,
        "parallel": 4,
    }


def _job_state(run_dir: Path) -> dict[str, Any] | None:
    path = run_dir / ".studio" / "job.json"
    job = _read_json(path)
    if not isinstance(job, dict):
        return None
    if job.get("status") == "running" and not _pid_alive(job.get("pid")):
        job = {**job, "status": "interrupted", "finished_at": job.get("finished_at") or _iso(path.stat().st_mtime)}
    return job


def _next_stage(
    *, blueprint: dict[str, Any], prepared: list[dict[str, Any]],
    rendered: list[dict[str, Any]], manifest: dict[str, Any], total: int,
) -> str | None:
    if not blueprint:
        return "1"
    if not prepared:
        return "2-prepare"
    if not rendered or len(rendered) < total:
        return "2-render"
    if any(not item.get("review_passed") for item in rendered):
        attempted = any(item.get("repair") for item in rendered)
        return "2-prepare" if attempted else "2-review"
    if not manifest:
        return "3"
    return None


def _stage_label(stage: str | None) -> str:
    return {
        None: "Complete",
        "1": "Plan",
        "2-prepare": "Prepare",
        "2-render": "Render",
        "2-review": "Review",
        "3": "Bundle",
    }.get(stage, stage or "Complete")


def _command_path(path: Path) -> str:
    """Prefer a portable project-relative path, retaining custom absolute roots."""
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _run_artifact_path(run_dir: Path, value: Any) -> Path | None:
    """Resolve a recorded run-relative path without allowing traversal.

    Older checkpoints wrote paths both as ``work/foo.html`` and as
    ``runs/<run-id>/work/foo.html``.  Normalize both forms before exposing an
    artifact to the Studio frontend.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("\\", "/")
    run_name = run_dir.name
    prefix = f"runs/{run_name}/"
    if raw.startswith(prefix):
        raw = raw[len(prefix):]
    candidate = Path(raw)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (run_dir / candidate).resolve()
    try:
        resolved.relative_to(run_dir.resolve())
    except ValueError:
        return None
    return resolved if resolved.is_file() else None


def _run_artifact_url(run_id: str, run_dir: Path, value: Any) -> str | None:
    path = _run_artifact_path(run_dir, value)
    if path is None:
        return None
    relative = path.relative_to(run_dir.resolve()).as_posix()
    return f"/runs/{run_id}/{relative}"


def _run_summary(run_dir: Path) -> dict[str, Any]:
    run_id = run_dir.name
    request = _read_json(run_dir / "request.json", {}) or {}
    blueprint = _read_json(run_dir / "blueprint" / "lesson_blueprint.json", {}) or {}
    prepared = _read_json(run_dir / "prepared_scenes.json", []) or []
    rendered = _read_json(run_dir / "rendered_scenes.json", []) or []
    prepared = _merge_scene_checkpoints(run_dir, "prepared", prepared)
    rendered = _merge_scene_checkpoints(run_dir, "rendered", rendered)
    manifest = _read_json(run_dir / "bundle" / "manifest.json", {}) or {}
    usage = _read_json(run_dir / "usage.json", {}) or {}
    warnings = _read_json(run_dir / "bundle" / "warnings.json", {}) or {}
    run_state = _read_json(run_dir / ".studio" / "run_state.json", {}) or {}
    request = request or _inferred_request(run_id, blueprint)

    planned_by_id = {str(s.get("id")): s for s in blueprint.get("scenes", []) if s.get("id")}
    prepared_by_id = {str(s.get("scene_id")): s for s in prepared if s.get("scene_id")}
    rendered_by_id = {str(s.get("scene_id")): s for s in rendered if s.get("scene_id")}
    ids = list(planned_by_id)
    ids.extend(i for i in prepared_by_id if i not in ids)
    ids.extend(i for i in rendered_by_id if i not in ids)

    scenes: list[dict[str, Any]] = []
    tools: Counter[str] = Counter()
    for scene_id in ids:
        plan = planned_by_id.get(scene_id, {})
        prep = prepared_by_id.get(scene_id, {})
        result = rendered_by_id.get(scene_id, {})
        scene_type = str(result.get("scene_type") or prep.get("scene_type") or plan.get("scene_type") or "unknown")
        tools[scene_type] += 1
        repair = result.get("repair") or {}
        guard = result.get("guard") or {}
        debug = result.get("debug") or {}
        findings = guard.get("findings") or []
        src = result.get("src")
        artifact_url = _run_artifact_url(run_id, run_dir, src)
        audio_src = result.get("audio_src")
        audio_url = (
            _run_artifact_url(run_id, run_dir, audio_src)
            if isinstance(audio_src, str) and not audio_src.lower().endswith(".mp4")
            else None
        )
        interactive_preview_url = _run_artifact_url(run_id, run_dir, debug.get("preview_html"))
        frame_urls = [
            url for frame in (debug.get("frames") or [])
            if (url := _run_artifact_url(run_id, run_dir, frame))
        ]
        state = "planned"
        if prep:
            state = "prepared"
        if result:
            state = "passed" if result.get("review_passed") else "needs_review"
        scenes.append({
            "id": scene_id,
            "title": plan.get("title") or scene_id,
            "type": scene_type,
            "state": state,
            "duration": result.get("duration"),
            "render_mode": result.get("render_mode") or scene_type,
            "src": src,
            "asset_url": artifact_url,
            "audio_url": audio_url,
            "frame_urls": frame_urls,
            "preview_url": f"/runs/{run_id}/bundle/index.html" if manifest else None,
            "interactive_preview_url": interactive_preview_url,
            "review_passed": bool(result.get("review_passed")),
            "review_error": bool(result.get("review_error")),
            "score": repair.get("score"),
            "issues": repair.get("blocking_issues") or repair.get("issues") or [],
            "guard_findings": findings,
            "attempt": prep.get("attempt", debug.get("prepared_attempt", 0)),
            "template": result.get("template") or prep.get("template") or plan.get("template"),
        })

    total = len(ids)
    passed = sum(1 for scene in scenes if scene["review_passed"])
    review_errors = sum(1 for scene in scenes if scene["review_error"])
    guard_findings = sum(len(scene["guard_findings"]) for scene in scenes)
    hitl_files = list((run_dir / "debug").glob("*_HITL.txt")) if (run_dir / "debug").is_dir() else []
    unresolved_hitl = 0
    for path in hitl_files:
        scene_id = path.name.removesuffix("_HITL.txt")
        current = rendered_by_id.get(scene_id)
        if current is None or not current.get("review_passed"):
            unresolved_hitl += 1
    next_stage = _next_stage(
        blueprint=blueprint, prepared=prepared, rendered=rendered,
        manifest=manifest, total=total,
    )
    stage_index = 0
    if blueprint:
        stage_index = 1
    if prepared:
        stage_index = 2
    if rendered:
        stage_index = 3
    if rendered and total and passed == total:
        stage_index = 4
    if manifest:
        stage_index = 5

    summary = usage.get("summary") or {}
    standalone = run_dir / "bundle" / "preview_standalone.html"
    bundle = run_dir / "bundle" / "index.html"
    job = _job_state(run_dir)
    running = bool(job and job.get("status") == "running")
    heartbeat = float(run_state.get("heartbeat_at") or 0)
    interrupted = bool(
        not running and (
            (job and job.get("status") == "interrupted")
            or (
                run_state.get("status") == "running"
                and heartbeat
                and (time.time() - heartbeat) > 120
            )
        )
    )
    health = "ready"
    if running:
        health = "running"
    elif interrupted:
        health = "interrupted"
    elif review_errors or unresolved_hitl:
        health = "attention"
    elif rendered and passed < total:
        health = "needs_review"
    elif manifest and (warnings.get("problems") or passed < total):
        health = "unreviewed_bundle"
    elif not manifest:
        health = "in_progress"

    recovery_stage = None if running else next_stage
    request_path = _command_path(run_dir / "request.json")
    command = None
    if recovery_stage:
        command = (
            f"python -m eduharness --request-json {request_path} "
            f"--run-dir {_command_path(run_dir)} --stage {recovery_stage}"
        )
    return {
        "id": run_id,
        "topic": blueprint.get("topic") or request.get("topic") or run_id,
        "audience": blueprint.get("audience") or request.get("audience") or "",
        "learning_goal": blueprint.get("learning_goal") or request.get("learning_goal") or "",
        "request": request,
        "request_persisted": (run_dir / "request.json").is_file(),
        "style": blueprint.get("style") or {},
        "updated_at": _iso(_latest_mtime(run_dir)),
        "health": health,
        "stage_index": stage_index,
        "next_stage": next_stage,
        "next_stage_label": _stage_label(next_stage),
        "recovery_command": command,
        "counts": {
            "total": total,
            "planned": len(planned_by_id),
            "prepared": len(prepared_by_id),
            "rendered": len(rendered_by_id),
            "passed": passed,
            "needs_review": max(0, len(rendered_by_id) - passed),
            "review_errors": review_errors,
            "guard_findings": guard_findings,
            "hitl": unresolved_hitl,
            "historical_hitl": len(hitl_files),
        },
        "tools": dict(tools),
        "scenes": scenes,
        "runtime": manifest.get("total_duration"),
        "timeline_count": len(manifest.get("timeline", [])),
        "cost_usd": summary.get("total_cost_usd"),
        "usage_calls": summary.get("calls"),
        "usage_by_kind": summary.get("by_kind") or {},
        "bundle_ready": bundle.is_file(),
        "bundle_url": f"/runs/{run_id}/bundle/index.html" if bundle.is_file() else None,
        "standalone_url": f"/runs/{run_id}/bundle/preview_standalone.html" if standalone.is_file() else None,
        "standalone_mb": round(standalone.stat().st_size / 1_000_000, 1) if standalone.is_file() else None,
        "warnings": warnings.get("problems") or [],
        "job": job,
        "run_state": run_state,
    }


def _merge_scene_checkpoints(
    run_dir: Path, kind: str, aggregate: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Read worker records too, including a batch interrupted before aggregation."""
    values = {
        str(item.get("scene_id")): item
        for item in aggregate
        if isinstance(item, dict) and item.get("scene_id")
    }
    directory = run_dir / ".studio" / "checkpoints" / kind
    if directory.is_dir():
        for path in sorted(directory.glob("*.json")):
            item = _read_json(path)
            if isinstance(item, dict) and item.get("scene_id"):
                values[str(item["scene_id"])] = item
    return list(values.values())


def scan_runs(runs_root: Path = RUNS_ROOT) -> list[dict[str, Any]]:
    """Return newest-first summaries without mutating any run artifacts."""
    if not runs_root.is_dir():
        return []
    runs = [
        _run_summary(path)
        for path in runs_root.iterdir()
        if path.is_dir() and _SAFE_ID.fullmatch(path.name)
        and any((path / marker).exists() for marker in (
            "request.json", "blueprint/lesson_blueprint.json", "prepared_scenes.json",
            "rendered_scenes.json", "bundle/manifest.json",
        ))
    ]
    return sorted(runs, key=lambda item: item.get("updated_at") or "", reverse=True)


def _capabilities() -> list[dict[str, Any]]:
    from ..stage2.adapters.manim import manim_available

    checks = {
        "remotion": (PROJECT_ROOT / "remotion_template" / "node_modules").is_dir(),
        # Match rendering's override and persistent-environment lookup as well
        # as PATH; the web service need not have the render venv activated.
        "manim": manim_available(),
        "image": bool(os.environ.get("EDUHARNESS_MEDIA_API_KEY") or os.environ.get("OPENAI_API_KEY")),
        "interactive": True,
        "narration": bool(os.environ.get("EDUHARNESS_MEDIA_API_KEY") or os.environ.get("OPENAI_API_KEY")),
    }
    labels = {
        "remotion": "Remotion",
        "manim": "Manim",
        "image": "AI Illustration",
        "interactive": "Interactive",
        "narration": "Narration",
    }
    return [{"id": key, "label": labels[key], "available": value} for key, value in checks.items()]


def _default_request() -> dict[str, Any]:
    return HarnessRequest(topic="").model_dump()


def _run_dir(runs_root: Path, run_id: str) -> Path:
    if not _SAFE_ID.fullmatch(run_id):
        raise ValueError("invalid run id")
    path = (runs_root / run_id).resolve()
    if path.parent != runs_root.resolve():
        raise ValueError("run path escapes runs directory")
    return path


def _start_job(
    runs_root: Path,
    run_id: str,
    stage: str,
    *,
    force: bool = False,
    api_key: str = "",
) -> dict[str, Any]:
    if stage not in _VALID_STAGES:
        raise ValueError("invalid pipeline stage")
    run_dir = _run_dir(runs_root, run_id)
    if not run_dir.is_dir():
        raise FileNotFoundError("run not found")
    with _JOB_LOCK:
        current = _job_state(run_dir)
        if current and current.get("status") == "running":
            raise RuntimeError("a pipeline job is already running for this build")
        request_path = run_dir / "request.json"
        if not request_path.is_file():
            blueprint = _read_json(run_dir / "blueprint" / "lesson_blueprint.json", {}) or {}
            request = HarnessRequest.model_validate(_inferred_request(run_id, blueprint))
            _atomic_json(request_path, request.model_dump())
        studio_dir = run_dir / ".studio"
        studio_dir.mkdir(parents=True, exist_ok=True)
        log_path = studio_dir / "job.log"
        command = [
            sys.executable, "-m", "eduharness", "--request-json", str(request_path),
            "--run-dir", str(run_dir), "--stage", stage,
        ]
        if force and stage in {"2-prepare", "2-render"}:
            command.append("--force")
        log_handle = log_path.open("a", encoding="utf-8", buffering=1)
        log_handle.write(
            f"\n[{datetime.now(timezone.utc).isoformat()}] $ "
            + " ".join(command) + "\n"
        )
        child_env = os.environ.copy()
        if api_key:
            # Keep the customer key in the child process only. It never enters
            # request.json, job.json, the command line, or job.log.
            child_env.update({
                "OPENAI_API_KEY": api_key,
                "OPENAI_BASE_URL": "https://api.openai.com/v1",
                "OPENAI_ORG_ID": "",
                "OPENAI_PROJECT_ID": "",
                "EDUHARNESS_TEXT_API_KEY": api_key,
                "EDUHARNESS_MEDIA_API_KEY": api_key,
                "EDUHARNESS_TEXT_BASE_URL": "https://api.openai.com/v1",
                "EDUHARNESS_MEDIA_BASE_URL": "https://api.openai.com/v1",
            })
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            env=child_env,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        metadata = {
            "status": "running",
            "stage": stage,
            "force": force,
            "pid": process.pid,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "exit_code": None,
            "command": command,
            "log": ".studio/job.log",
        }
        _atomic_json(studio_dir / "job.json", metadata)

        def reap() -> None:
            code = process.wait()
            log_handle.close()
            completed = {
                **metadata,
                "status": "complete" if code == 0 else "failed",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "exit_code": code,
            }
            _atomic_json(studio_dir / "job.json", completed)

        threading.Thread(target=reap, daemon=True, name=f"studio-{run_id}").start()
        return metadata


def _tail(path: Path, limit: int = 40_000) -> str:
    if not path.is_file():
        return ""
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - limit))
        data = handle.read()
    return data.decode("utf-8", errors="replace")


class StudioHandler(RangeHandler):
    """JSON endpoints, packaged frontend assets, and range-served run media."""

    server_version = "EduCastStudio/1.0"
    runs_root: Path = RUNS_ROOT

    def _send_json(self, value: Any, status: int = 200) -> None:
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _send_asset(self, name: str, content_type: str) -> None:
        path = ASSET_DIR / name
        if not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _send_asset_path(self, relative: str) -> None:
        """Serve a bundled Studio asset while keeping traversal impossible."""
        candidate = (ASSET_DIR / "assets" / unquote(relative)).resolve()
        try:
            candidate.relative_to((ASSET_DIR / "assets").resolve())
        except ValueError:
            self.send_error(404)
            return
        if not candidate.is_file():
            self.send_error(404)
            return
        data = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("invalid content length") from exc
        if length <= 0 or length > 2_000_000:
            raise ValueError("request body must be between 1 byte and 2 MB")
        try:
            value = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def _send_run_file(self, run_id: str, relative: str) -> None:
        """Serve a run artifact from the configured runs root with byte ranges."""
        run_dir = _run_dir(self.runs_root, unquote(run_id))
        candidate = (run_dir / unquote(relative)).resolve()
        try:
            candidate.relative_to(run_dir.resolve())
        except ValueError as exc:
            raise ValueError("artifact path escapes run directory") from exc
        if not candidate.is_file():
            self.send_error(404)
            return
        size = candidate.stat().st_size
        range_header = self.headers.get("Range")
        start, end, status = 0, size - 1, 200
        if range_header:
            match = _RANGE.match(range_header.strip())
            if match:
                start_s, end_s = match.groups()
                if start_s:
                    start = int(start_s)
                    end = int(end_s) if end_s else size - 1
                else:
                    start = max(0, size - int(end_s or 0))
                if start >= size or start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                end = min(end, size - 1)
                status = 206
        length = max(0, end - start + 1)
        self.send_response(status)
        self.send_header("Content-Type", mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        with candidate.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining:
                chunk = handle.read(min(65536, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def send_head(self):
        """Support HEAD and Range requests for both Studio assets and run media."""
        self._range_left = None
        path = urlparse(self.path).path
        assets = {
            "/": (ASSET_DIR / "index.html", "text/html; charset=utf-8"),
            "/index.html": (ASSET_DIR / "index.html", "text/html; charset=utf-8"),
            "/assets/app.css": (ASSET_DIR / "app.css", "text/css; charset=utf-8"),
            "/assets/app.js": (ASSET_DIR / "app.js", "text/javascript; charset=utf-8"),
            "/assets/landing.js": (ASSET_DIR / "landing.js", "text/javascript; charset=utf-8"),
        }
        if path in assets:
            file_path, content_type = assets[path]
            handle = file_path.open("rb")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(file_path.stat().st_size))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            return handle
        if path.startswith("/assets/"):
            relative = path.removeprefix("/assets/")
            candidate = (ASSET_DIR / "assets" / unquote(relative)).resolve()
            try:
                candidate.relative_to((ASSET_DIR / "assets").resolve())
            except ValueError:
                candidate = None
            if candidate is not None and candidate.is_file():
                handle = candidate.open("rb")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")
                self.send_header("Content-Length", str(candidate.stat().st_size))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                return handle
        if path.startswith("/runs/"):
            parts = path.split("/", 3)
            if len(parts) == 4 and parts[2] and parts[3]:
                try:
                    run_dir = _run_dir(self.runs_root, unquote(parts[2]))
                    candidate = (run_dir / unquote(parts[3])).resolve()
                    candidate.relative_to(run_dir.resolve())
                    if candidate.is_file():
                        size = candidate.stat().st_size
                        start, end, status = 0, size - 1, HTTPStatus.OK
                        match = _RANGE.match((self.headers.get("Range") or "").strip())
                        if match:
                            start_s, end_s = match.groups()
                            if start_s:
                                start = int(start_s)
                                end = int(end_s) if end_s else size - 1
                            else:
                                start = max(0, size - int(end_s or 0))
                            if start >= size or start > end:
                                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                                self.send_header("Content-Range", f"bytes */{size}")
                                self.end_headers()
                                return None
                            end = min(end, size - 1)
                            status = HTTPStatus.PARTIAL_CONTENT
                        handle = candidate.open("rb")
                        handle.seek(start)
                        self._range_left = end - start + 1
                        self.send_response(status)
                        self.send_header("Content-Type", mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")
                        self.send_header("Content-Length", str(self._range_left))
                        self.send_header("Accept-Ranges", "bytes")
                        if status == HTTPStatus.PARTIAL_CONTENT:
                            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                        self.end_headers()
                        return handle
                except ValueError:
                    pass
        self.send_error(HTTPStatus.NOT_FOUND)
        return None

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            self._send_asset("index.html", "text/html; charset=utf-8")
            return
        if path == "/assets/app.css":
            self._send_asset("app.css", "text/css; charset=utf-8")
            return
        if path == "/assets/app.js":
            self._send_asset("app.js", "text/javascript; charset=utf-8")
            return
        if path == "/assets/landing.js":
            self._send_asset("landing.js", "text/javascript; charset=utf-8")
            return
        if path.startswith("/assets/"):
            self._send_asset_path(path.removeprefix("/assets/"))
            return
        if path == "/api/state":
            runs = scan_runs(self.runs_root)
            self._send_json({
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "runs": runs,
                "capabilities": _capabilities(),
                "defaults": _default_request(),
                "api_configured": bool(
                    os.environ.get("EDUHARNESS_TEXT_API_KEY") or os.environ.get("OPENAI_API_KEY")
                ),
            })
            return
        match = re.fullmatch(r"/api/runs/([^/]+)/log", path)
        if match:
            try:
                run_dir = _run_dir(self.runs_root, unquote(match.group(1)))
                self._send_json({"log": _tail(run_dir / ".studio" / "job.log")})
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
            return
        if path.startswith("/runs/"):
            parts = path.split("/", 3)
            if len(parts) < 4 or not parts[2] or not parts[3]:
                self.send_error(404)
                return
            try:
                self._send_run_file(parts[2], parts[3])
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            body = self._body()
            api_key = (
                normalize_user_api_key(body.pop("openai_api_key"))
                if "openai_api_key" in body else ""
            )
            if path == "/api/runs":
                request = HarnessRequest.model_validate(body)
                run_id = request.request_id
                if not _SAFE_ID.fullmatch(run_id):
                    raise ValueError("request_id may contain only letters, numbers, dash, and underscore")
                run_dir = _run_dir(self.runs_root, run_id)
                run_dir.mkdir(parents=True, exist_ok=True)
                _atomic_json(run_dir / "request.json", request.model_dump())
                self._send_json({"ok": True, "run": _run_summary(run_dir)}, 201)
                return
            match = re.fullmatch(r"/api/runs/([^/]+)/jobs", path)
            if match:
                stage = str(body.get("stage", ""))
                job = _start_job(
                    self.runs_root,
                    unquote(match.group(1)),
                    stage,
                    force=bool(body.get("force", False)),
                    api_key=api_key,
                )
                self._send_json({"ok": True, "job": job}, 202)
                return
            self.send_error(404)
        except FileNotFoundError as exc:
            self._send_json({"error": str(exc)}, 404)
        except RuntimeError as exc:
            self._send_json({"error": str(exc)}, 409)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 400)

    def log_message(self, format: str, *args: Any) -> None:
        if os.environ.get("EDUHARNESS_STUDIO_VERBOSE"):
            super().log_message(format, *args)


def serve(
    *, runs_root: Path = RUNS_ROOT, host: str = "127.0.0.1", port: int = 8080,
) -> ThreadingHTTPServer:
    runs_root = runs_root.resolve()
    runs_root.mkdir(parents=True, exist_ok=True)

    class BoundHandler(StudioHandler):
        pass

    BoundHandler.runs_root = runs_root
    return ThreadingHTTPServer((host, port), lambda *args, **kwargs: BoundHandler(
        *args, directory=str(PROJECT_ROOT), **kwargs
    ))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="eduharness.studio")
    parser.add_argument("--runs-dir", default=str(RUNS_ROOT))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)
    server = serve(runs_root=Path(args.runs_dir), host=args.host, port=args.port)
    print(
        f"EduCast Render Studio → http://{args.host}:{server.server_port}/\n"
        f"Runs → {Path(args.runs_dir).resolve()}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
