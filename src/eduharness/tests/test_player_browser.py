from __future__ import annotations

import json
import subprocess
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from eduharness.schema import LessonBlueprint, RenderedScene, SceneBrief, SceneType
from eduharness.stage3.bundler import build_bundle


def test_video_overlay_pauses_and_resumes(tmp_path) -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    from eduharness.stage2.media import ffmpeg_available, ffmpeg_bin

    if not ffmpeg_available():
        pytest.skip("ffmpeg is unavailable")

    (tmp_path / "media").mkdir()
    (tmp_path / "interactive").mkdir()
    subprocess.run(
        [
            ffmpeg_bin(), "-y", "-f", "lavfi", "-i", "color=c=black:s=640x360:d=2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(tmp_path / "media" / "video.mp4"),
        ],
        check=True,
        capture_output=True,
    )
    (tmp_path / "interactive" / "check.json").write_text(
        json.dumps(
            {
                "template": "multiple_choice",
                "parameters": {
                    "question": "<img src=x onerror='window.__xss=true'>",
                    "choices": ["Correct", "Wrong"],
                    "correct_index": 0,
                    "explanation": "Good",
                },
            }
        ),
        encoding="utf-8",
    )
    blueprint = LessonBlueprint(
        topic="Browser test", audience="students", learning_goal="test",
        scenes=[
            SceneBrief(
                id="video", title="Video", scene_type=SceneType.MANIM,
                visual_brief="video", target_seconds=2,
            ),
            SceneBrief(
                id="check", title="Check", scene_type=SceneType.INTERACTIVE,
                visual_brief="check", template="multiple_choice",
                trigger_scene_id="video", trigger_at_seconds=0.3,
            ),
        ],
    )
    rendered = [
        RenderedScene(
            scene_id="video", scene_type=SceneType.MANIM,
            src="media/video.mp4", duration=2, review_passed=True,
        ),
        RenderedScene(
            scene_id="check", scene_type=SceneType.INTERACTIVE,
            src="interactive/check.json", template="multiple_choice",
            review_passed=True,
        ),
    ]
    build_bundle(tmp_path, blueprint, rendered, "browser-test")

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(tmp_path / "bundle"), **kwargs)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as runtime:
            try:
                browser = runtime.chromium.launch(
                    args=["--autoplay-policy=no-user-gesture-required"]
                )
            except Exception as exc:
                pytest.skip(f"Chromium is unavailable: {exc}")
            page = browser.new_page()
            page.goto(
                f"http://127.0.0.1:{server.server_port}/index.html",
                wait_until="networkidle",
            )
            page.wait_for_selector('#stage[data-state="INTERACTIVE_PAUSE"]', timeout=5000)
            assert page.evaluate("window.__xss") is None
            page.get_by_role("button", name="Correct").click()
            # the runtime shows the explanation first; Continue resumes the video
            page.get_by_role("button", name="Continue").click()
            page.wait_for_selector('#stage[data-state="PLAYING_MEDIA"]', timeout=3000)
            page.wait_for_selector('#stage[data-state="FINISHED"]', timeout=5000)
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
