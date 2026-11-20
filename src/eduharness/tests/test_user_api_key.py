from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from eduharness.studio import public, server as studio


@contextmanager
def _running_server(factory, runs_root):
    server = factory(runs_root=runs_root, host="127.0.0.1", port=0)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True,
    )
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def _post(base, path, body):
    return urlopen(Request(
        base + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    ))


def test_public_lesson_key_is_forwarded_without_persistence(tmp_path, monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_start(runs_root, run_id, stage, *, force=False, api_key=""):
        captured.update({"run_id": run_id, "stage": stage, "api_key": api_key})
        return {"status": "running", "stage": stage, "pid": 0}

    monkeypatch.setattr(public, "_start_job", fake_start)
    server = public.serve(runs_root=tmp_path, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    key = "sk-proj-" + "a" * 40
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/lessons",
            data=json.dumps({"topic": "Vectors", "openai_api_key": key}).encode(),
            headers={"Content-Type": "application/json", "Idempotency-Key": "test-key"},
            method="POST",
        )
        assert urlopen(request).status == 202
        assert captured["api_key"] == key
        run_dir = tmp_path / captured["run_id"]
        saved = json.loads((run_dir / "request.json").read_text())
        assert "openai_api_key" not in saved
        assert key not in (run_dir / "request.json").read_text()
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("api_key", [None, "sk-proj-" + "b" * 40])
def test_studio_jobs_forward_optional_user_key(tmp_path, monkeypatch, api_key) -> None:
    captured = {}

    def fake_start(runs_root, run_id, stage, *, force=False, api_key=""):
        captured.update({"run_id": run_id, "stage": stage, "api_key": api_key})
        return {"status": "running", "stage": stage, "pid": 0}

    monkeypatch.setattr(studio, "_start_job", fake_start)
    body = {"stage": "all"}
    if api_key is not None:
        body["openai_api_key"] = api_key
    with _running_server(studio.serve, tmp_path) as base:
        with _post(base, "/api/runs/example/jobs", body) as response:
            assert response.status == 202
    assert captured == {"run_id": "example", "stage": "all", "api_key": api_key or ""}


@pytest.mark.parametrize("path", ["/api/runs", "/api/runs/example/jobs"])
def test_studio_rejects_explicit_invalid_key(tmp_path, monkeypatch, path) -> None:
    def unexpected_start(*args, **kwargs):
        pytest.fail("Invalid credentials must not start a job")

    monkeypatch.setattr(studio, "_start_job", unexpected_start)
    with _running_server(studio.serve, tmp_path) as base:
        for value in (None, False, 0, {}, [], "", "  ", "invalid"):
            with pytest.raises(HTTPError) as error:
                _post(base, path, {
                    "request_id": "example", "topic": "Vectors", "stage": "all",
                    "openai_api_key": value,
                })
            assert error.value.code == 400
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("path", ["/api/lessons", "/api/lessons/example/retry"])
def test_public_requires_user_key_even_with_server_credentials(tmp_path, monkeypatch, path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-" + "s" * 40)
    monkeypatch.setenv("EDUHARNESS_TEXT_API_KEY", "sk-proj-" + "t" * 40)

    def unexpected_start(*args, **kwargs):
        pytest.fail("Missing or invalid user credentials must not start a job")

    monkeypatch.setattr(public, "_start_job", unexpected_start)
    missing = object()
    with _running_server(public.serve, tmp_path) as base:
        for value in (missing, None, False, 0, {}, [], "", "  ", "invalid"):
            body = {"topic": "Vectors"}
            if value is not missing:
                body["openai_api_key"] = value
            with pytest.raises(HTTPError) as error:
                _post(base, path, body)
            assert error.value.code == 400
    assert not list(tmp_path.iterdir())


def test_public_retry_forwards_new_key_without_persistence(tmp_path, monkeypatch) -> None:
    run_dir = tmp_path / "example"
    studio._atomic_json(run_dir / "request.json", {"request_id": "example", "topic": "Vectors"})
    studio._atomic_json(run_dir / ".studio/public.json", {})
    captured = {}

    def fake_start(runs_root, run_id, stage, *, force=False, api_key=""):
        captured.update({"run_id": run_id, "stage": stage, "api_key": api_key})
        return {"status": "running", "stage": stage, "pid": 0}

    monkeypatch.setattr(public, "_start_job", fake_start)
    key = "sk-proj-" + "r" * 40
    with _running_server(public.serve, tmp_path) as base:
        with _post(base, "/api/lessons/example/retry", {"openai_api_key": key}) as response:
            assert response.status == 202
    assert captured == {"run_id": "example", "stage": "all", "api_key": key}
    for path in run_dir.rglob("*.json"):
        assert key not in path.read_text()


def test_job_key_stays_in_child_environment(tmp_path, monkeypatch) -> None:
    key = "sk-proj-" + "u" * 40
    monkeypatch.setenv("OPENAI_API_KEY", "server-key")
    monkeypatch.setenv("EDUHARNESS_TEXT_API_KEY", "server-text-key")
    monkeypatch.setenv("EDUHARNESS_MEDIA_API_KEY", "server-media-key")
    monkeypatch.setenv("EDUHARNESS_TEXT_BASE_URL", "https://text.invalid/v1")
    monkeypatch.setenv("EDUHARNESS_MEDIA_BASE_URL", "https://media.invalid/v1")
    original_env = os.environ.copy()
    run_dir = tmp_path / "example"
    run_dir.mkdir()
    studio._atomic_json(run_dir / "request.json", {"request_id": "example", "topic": "Vectors"})
    captured = {}

    class FakeProcess:
        pid = 12345

        def wait(self):
            return 0

    def fake_popen(command, **kwargs):
        captured.update({"command": command, **kwargs})
        return FakeProcess()

    class ImmediateThread:
        def __init__(self, *, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(studio.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(studio.threading, "Thread", ImmediateThread)
    job = studio._start_job(tmp_path, "example", "all", api_key=key)
    for name in ("OPENAI_API_KEY", "EDUHARNESS_TEXT_API_KEY", "EDUHARNESS_MEDIA_API_KEY"):
        assert captured["env"][name] == key
    for name in ("EDUHARNESS_TEXT_BASE_URL", "EDUHARNESS_MEDIA_BASE_URL"):
        assert captured["env"][name] == "https://api.openai.com/v1"
    assert os.environ == original_env
    assert key not in json.dumps(captured["command"])
    assert key not in json.dumps(job)
    for path in (run_dir / "request.json", run_dir / ".studio/job.json", run_dir / ".studio/job.log"):
        assert key not in path.read_text()
