from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import pytest

from eduharness.config import Config
from eduharness.schema import HarnessRequest, PreparedScene, SceneType
from eduharness.stage2 import workflow
from eduharness.studio.server import _command_path, scan_runs, serve


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_scan_runs_reports_real_checkpoint_state(tmp_path) -> None:
    run = tmp_path / "lesson_one"
    _write(run / "request.json", {"request_id": "lesson_one", "topic": "Vectors"})
    _write(
        run / "blueprint" / "lesson_blueprint.json",
        {
            "topic": "Vectors",
            "audience": "students",
            "learning_goal": "Add vectors",
            "scenes": [
                {"id": "a", "title": "Intro", "scene_type": "remotion"},
                {"id": "b", "title": "Try", "scene_type": "interactive"},
            ],
        },
    )
    _write(run / "prepared_scenes.json", [{"scene_id": "a", "scene_type": "remotion"}])
    _write(
        run / ".studio" / "checkpoints" / "rendered" / "a.json",
        {
            "scene_id": "a", "scene_type": "remotion", "src": "media/a.mp4",
            "review_passed": False,
        },
    )
    _write(run / ".studio" / "checkpoints" / "prepared" / "b.json", {"scene_id": "b", "scene_type": "interactive"})

    result = scan_runs(tmp_path)[0]
    assert result["id"] == "lesson_one"
    assert result["counts"]["rendered"] == 1
    assert result["tools"] == {"remotion": 1, "interactive": 1}
    assert result["next_stage"] == "2-render"
    assert "--stage 2-render" in result["recovery_command"]


def test_scan_runs_marks_stale_running_checkpoint_as_interrupted(tmp_path) -> None:
    run = tmp_path / "interrupted"
    _write(run / "request.json", {"request_id": "interrupted", "topic": "Interrupted"})
    _write(run / "blueprint" / "lesson_blueprint.json", {"topic": "Interrupted", "scenes": []})
    _write(
        run / ".studio" / "run_state.json",
        {"stage": "2-render", "status": "running", "heartbeat_at": time.time() - 500},
    )

    result = scan_runs(tmp_path)[0]
    assert result["health"] == "interrupted"
    assert result["next_stage"] == "2-prepare"


def test_completed_bundle_defaults_to_ready(tmp_path) -> None:
    run = tmp_path / "complete"
    _write(run / "request.json", {"request_id": "complete", "topic": "Complete"})
    _write(
        run / "blueprint" / "lesson_blueprint.json",
        {"topic": "Complete", "scenes": [{"id": "a", "title": "A", "scene_type": "image"}]},
    )
    _write(
        run / "rendered_scenes.json",
        [{"scene_id": "a", "scene_type": "image", "src": "media/a.png", "review_passed": True}],
    )
    (run / "bundle").mkdir(parents=True)
    _write(run / "bundle" / "manifest.json", {"timeline": [], "total_duration": 0})
    (run / "bundle" / "index.html").write_text("ok", encoding="utf-8")
    assert scan_runs(tmp_path)[0]["health"] == "ready"


def test_custom_recovery_path_stays_absolute(tmp_path) -> None:
    path = tmp_path / "runs" / "lesson" / "request.json"
    assert _command_path(path) == str(path.resolve())


def test_per_scene_checkpoint_survives_without_aggregate(tmp_path) -> None:
    request = HarnessRequest(request_id="resume", topic="Resume")
    cfg = Config(request=request, run_dir=tmp_path)
    value = PreparedScene(scene_id="first", scene_type=SceneType.INTERACTIVE)
    workflow._write_scene_checkpoint(cfg, "prepared", value)

    assert not cfg.prepared_path.exists()
    assert workflow.has_prepared_checkpoint(cfg)
    assert workflow.load_prepared(cfg) == [value]
    state = json.loads((tmp_path / ".studio" / "run_state.json").read_text())
    assert state["completed_prepared"] == 1


def test_studio_http_api_and_path_guard(tmp_path) -> None:
    server = serve(runs_root=tmp_path, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        assert urlopen(base + "/").status == 200
        request = Request(
            base + "/api/runs",
            data=json.dumps({"request_id": "new_run", "topic": "A lesson"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        assert urlopen(request).status == 201
        saved = json.loads((tmp_path / "new_run" / "request.json").read_text())
        assert saved["topic"] == "A lesson"

        bad = Request(
            base + "/api/runs",
            data=json.dumps({"request_id": "../escape", "topic": "Bad"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as exc:
            urlopen(bad)
        assert exc.value.code == 400
        assert not (tmp_path.parent / "escape").exists()
        assets = {
            "/assets/characters/character-1.png": "image/png",
            "/assets/landing.js": "text/javascript",
            "/assets/brand.svg": "image/svg+xml",
            "/assets/lesson-lever.svg": "image/svg+xml",
            "/assets/fonts/dmsans-400.ttf": "font/ttf",
        }
        for path, content_type in assets.items():
            with urlopen(base + path) as response:
                assert response.status == 200, path
                assert response.headers.get_content_type() == content_type, path
                content = response.read()
                assert content, path
                assert int(response.headers["Content-Length"]) == len(content), path
            with urlopen(Request(base + path, method="HEAD")) as response:
                assert response.status == 200, path
                assert response.headers.get_content_type() == content_type, path
                assert int(response.headers["Content-Length"]) == len(content), path
                assert response.read() == b"", path

        for path in (
            "/assets/%2e%2e/server.py",
            "/assets/%2e%2e/%2e%2e/config.py",
        ):
            for method in ("GET", "HEAD"):
                with pytest.raises(HTTPError) as exc:
                    urlopen(Request(base + path, method=method))
                assert exc.value.code == 404, (method, path)
    finally:
        server.shutdown()
        server.server_close()


class _Homepage(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__()
        self.elements: list[tuple[str, dict]] = []
        self.feed(source)

    def handle_starttag(self, tag, attrs) -> None:
        self.elements.append((tag, dict(attrs)))


def test_studio_homepage_preserves_navigation_and_build_controls() -> None:
    html = Path("eduharness/studio/index.html").read_text(encoding="utf-8")
    page = _Homepage(html)
    assert any(tag == "html" and attrs.get("lang") == "en" for tag, attrs in page.elements)
    ids = {attrs["id"] for _, attrs in page.elements if "id" in attrs}
    assert {
        "demo", "pipeline", "studio", "new-build", "hero-new-build",
        "pipeline-new-build", "run-search", "run-list", "request-form",
        "save-draft", "save-and-plan", "open-player", "open-standalone",
        "metric-scenes", "scene-list", "preview-stage",
    } <= ids
    links = {attrs.get("href") for tag, attrs in page.elements if tag == "a"}
    assert {"#demo", "#pipeline", "#studio"} <= links
    assert not any("\u4e00" <= char <= "\u9fff" for char in html)


def test_demo_embeds_complete_lesson_player() -> None:
    page = _Homepage(Path("eduharness/studio/index.html").read_text(encoding="utf-8"))
    frame = next(attrs for tag, attrs in page.elements
                 if tag == "iframe" and attrs.get("id") == "demo-frame")
    assert frame.get("title"), "the embedded player needs an accessible label"
    assert "allowfullscreen" in frame
    cards = [attrs for tag, attrs in page.elements
             if tag == "button" and attrs.get("data-run")]
    assert cards, "visitors must be able to select complete example lessons"
    assert frame["src"] in {card["data-src"] for card in cards}
    for card in cards:
        source = urlsplit(card["data-src"])
        assert not source.scheme and not source.netloc
        assert re.fullmatch(r"/runs/[\w.-]+/bundle/index\.html", source.path), source.path
        assert source.path == f'/runs/{card["data-run"]}/bundle/index.html'
    full_player = next(attrs for tag, attrs in page.elements
                       if tag == "a" and attrs.get("id") == "demo-open")
    assert urlsplit(full_player["href"]).path == urlsplit(frame["src"]).path


def test_player_contains_resume_snapshot_contract() -> None:
    from eduharness.stage3.player import PLAYER_JS, shell_html

    assert "resume:v1" in PLAYER_JS
    assert 'get("fresh") === "1"' in PLAYER_JS
    assert 'localStorage.setItem(resumeKey' in PLAYER_JS
    assert 'addEventListener("pagehide"' in PLAYER_JS
    html = shell_html("Topic", scripts="")
    assert 'id="resume-last"' in html
    assert 'id="restart-lesson"' in html
    assert 'class="kpi-strip"' not in html
    assert "Practice checkpoints" not in html


def test_recovery_only_targets_missing_prepared_scenes(tmp_path, monkeypatch) -> None:
    request = HarnessRequest(request_id="partial", topic="Partial")
    cfg = Config(request=request, run_dir=tmp_path)
    blueprint = __import__("eduharness.schema", fromlist=["LessonBlueprint"]).LessonBlueprint(
        topic="Partial", audience="students", learning_goal="goal", scenes=[
            {"id": "a", "title": "A", "scene_type": "interactive", "visual_brief": "a"},
            {"id": "b", "title": "B", "scene_type": "interactive", "visual_brief": "b"},
        ]
    )
    first = PreparedScene(scene_id="a", scene_type=SceneType.INTERACTIVE)
    workflow._write_scene_checkpoint(cfg, "prepared", first)
    called = []

    def fake_prepare(*args, **kwargs):
        called.extend(sorted(kwargs["only_scene_ids"] or set()))
        return PreparedScene(scene_id="b", scene_type=SceneType.INTERACTIVE)

    monkeypatch.setattr(workflow, "prepare_all", fake_prepare)
    # No rendered checkpoint means this is the partial-prepare recovery branch.
    from eduharness import pipeline
    pipeline.stage2_prepare(cfg, provider=object(), blueprint=blueprint)
    assert called == ["b"]
