"""Which external binaries the adapters pick when several are on disk."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from eduharness.stage2.adapters.manim import manim_available, manim_bin
from eduharness.stage2.adapters.remotion import browser_executable, chrome_is_complete


def _chrome(path: Path, *, complete: bool) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x7fELF fake chrome")
    path.chmod(0o755)
    if complete:
        (path.parent / "icudtl.dat").write_bytes(b"icu")
    return path


@pytest.fixture
def template(tmp_path, monkeypatch) -> Path:
    # Keep the machine's own Playwright cache out of the candidate list.
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "no-playwright"))
    monkeypatch.delenv("EDUHARNESS_BROWSER_EXECUTABLE", raising=False)
    path = tmp_path / "proj" / "remotion_template"
    path.mkdir(parents=True)
    return path


def _own_download(template: Path) -> Path:
    return template / "node_modules" / ".remotion" / "chrome-headless-shell" / "chrome-headless-shell"


def _bundled(template: Path) -> Path:
    return (template.parent / "eduharness" / "runtime"
            / "chrome-headless-shell-linux64" / "chrome-headless-shell")


def test_complete_bundle_wins_over_a_partial_download(template):
    """A binary unzipped without icudtl.dat used to shadow a working bundle.

    It answers --version, so it looks fine, then fails at launch and every
    Remotion scene silently degrades to a static slide.
    """
    _chrome(_own_download(template), complete=False)
    good = _chrome(_bundled(template), complete=True)
    assert browser_executable(template) == str(good)


def test_own_download_is_preferred_when_it_is_complete(template):
    good = _chrome(_own_download(template), complete=True)
    _chrome(_bundled(template), complete=True)
    assert browser_executable(template) == str(good)


def test_partial_download_is_still_returned_when_it_is_all_there_is(template):
    """No complete build anywhere: fail where we always failed, not earlier."""
    torso = _chrome(_own_download(template), complete=False)
    assert browser_executable(template) == str(torso)


def test_no_browser_at_all(template):
    assert browser_executable(template) is None


def test_explicit_override_is_taken_as_given(template, tmp_path, monkeypatch):
    _chrome(_bundled(template), complete=True)
    override = _chrome(tmp_path / "elsewhere" / "chrome", complete=False)
    monkeypatch.setenv("EDUHARNESS_BROWSER_EXECUTABLE", str(override))
    assert browser_executable(template) == str(override)


def test_chrome_is_complete_reads_the_resource_beside_the_binary(tmp_path):
    assert chrome_is_complete(_chrome(tmp_path / "full" / "chrome", complete=True))
    assert not chrome_is_complete(_chrome(tmp_path / "torso" / "chrome", complete=False))
    assert not chrome_is_complete(tmp_path / "missing" / "chrome")


def test_the_real_project_bundle_is_complete_if_present():
    """Guards the actual tree on this host — skipped where it is not staged."""
    from eduharness.stage2.adapters.remotion import _browser_candidates, template_root

    template = template_root()
    if not template.is_dir():
        pytest.skip("remotion_template is not present")
    candidates = _browser_candidates(template)
    if not candidates:
        pytest.skip("no Chrome build staged on this host")
    chosen = browser_executable(template)
    assert chosen is not None
    assert chrome_is_complete(Path(chosen)), f"{chosen} has no icudtl.dat beside it"
    assert os.access(chosen, os.X_OK)


def test_manim_override_is_used_when_executable(tmp_path, monkeypatch):
    binary = tmp_path / "manim"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    monkeypatch.setenv("EDUHARNESS_MANIM", str(binary))
    assert manim_bin() == str(binary)
    assert manim_available()


def test_manim_override_that_is_not_executable_falls_through(tmp_path, monkeypatch):
    dud = tmp_path / "manim"
    dud.write_text("not executable")
    monkeypatch.setenv("EDUHARNESS_MANIM", str(dud))
    monkeypatch.setattr("eduharness.stage2.adapters.manim.shutil.which", lambda name: "/opt/bin/manim")
    assert manim_bin() == "/opt/bin/manim"


def test_manim_prefers_path_over_the_project_venv(monkeypatch):
    monkeypatch.delenv("EDUHARNESS_MANIM", raising=False)
    monkeypatch.setattr("eduharness.stage2.adapters.manim.shutil.which", lambda name: "/usr/local/bin/manim")
    assert manim_bin() == "/usr/local/bin/manim"


def test_manim_missing_everywhere_reports_unavailable(monkeypatch, tmp_path):
    from eduharness.stage2.adapters import manim as manim_module

    monkeypatch.delenv("EDUHARNESS_MANIM", raising=False)
    monkeypatch.setattr(manim_module.shutil, "which", lambda name: None)
    # The venv lookup walks up from the module file; point it at a tree that
    # holds no .render-env.
    elsewhere = tmp_path / "pkg" / "eduharness" / "stage2" / "adapters" / "manim.py"
    elsewhere.parent.mkdir(parents=True)
    monkeypatch.setattr(manim_module, "__file__", str(elsewhere))
    assert manim_bin() is None
    assert not manim_available()


def test_manim_found_in_the_project_venv_without_sourcing_env(monkeypatch, tmp_path):
    """A host reset leaves the venv on the volume but nothing on PATH."""
    from eduharness.stage2.adapters import manim as manim_module

    monkeypatch.delenv("EDUHARNESS_MANIM", raising=False)
    monkeypatch.setattr(manim_module.shutil, "which", lambda name: None)
    module_file = tmp_path / "pkg" / "eduharness" / "stage2" / "adapters" / "manim.py"
    module_file.parent.mkdir(parents=True)
    monkeypatch.setattr(manim_module, "__file__", str(module_file))
    venv_manim = tmp_path / "pkg" / "eduharness" / ".render-env" / "bin" / "manim"
    venv_manim.parent.mkdir(parents=True)
    venv_manim.write_text("#!/bin/sh\n")
    venv_manim.chmod(0o755)
    assert manim_bin() == str(venv_manim)


@pytest.mark.parametrize('name', ['ffmpeg', 'ffprobe'])
def test_media_tools_find_persistent_store_without_env_script(monkeypatch, tmp_path, name):
    from eduharness.stage2 import media

    module_file = tmp_path / 'education_video' / 'eduharness' / 'eduharness' / 'stage2' / 'media.py'
    module_file.parent.mkdir(parents=True)
    monkeypatch.setattr(media, '__file__', str(module_file))
    monkeypatch.setattr(media, '_TOOL_CACHE', {})
    monkeypatch.delenv(f'EDUHARNESS_{name.upper()}', raising=False)
    monkeypatch.delenv('EDUHARNESS_STORE', raising=False)
    monkeypatch.setenv('PATH', str(tmp_path / 'empty'))
    tool = tmp_path / 'eduharness' / 'eduharness' / 'bin' / name
    tool.parent.mkdir(parents=True, exist_ok=True)
    tool.write_text('#!/bin/sh\nexit 0\n')
    tool.chmod(0o755)

    # Reject any tools from the host: this regression exercises the persistent
    # layout after a host restart has removed ffmpeg from PATH.
    from types import SimpleNamespace
    monkeypatch.setattr(media.subprocess, 'run', lambda cmd, **kw: SimpleNamespace(
        returncode=0 if cmd[0] == str(tool) else 1))
    assert media._resolve_tool(name) == str(tool)
