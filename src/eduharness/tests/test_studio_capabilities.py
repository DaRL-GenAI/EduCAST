"""The UI must advertise the same Manim installation used by rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

from eduharness.stage2.adapters import manim
from eduharness.studio.server import _capabilities


@pytest.fixture
def isolated_manim_tree(tmp_path, monkeypatch) -> tuple[Path, Path]:
    # Both managed-installation candidates stay under tmp_path, so a real
    # installation on the host cannot conceal a missing-tool regression.
    module_file = (
        tmp_path / "workspace" / "education_video" / "eduharness"
        / "eduharness" / "stage2" / "adapters" / "manim.py"
    )
    module_file.parent.mkdir(parents=True)
    monkeypatch.setattr(manim, "__file__", str(module_file))
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    monkeypatch.delenv("EDUHARNESS_MANIM", raising=False)
    return (
        module_file.parents[2] / ".render-env" / "bin" / "manim",
        tmp_path / "workspace" / "eduharness" / "eduharness"
        / ".render-env" / "bin" / "manim",
    )


def _manim_capability() -> bool:
    return next(item["available"] for item in _capabilities() if item["id"] == "manim")


@pytest.mark.parametrize("installation", [0, 1], ids=["project", "persistent"])
def test_managed_manim_is_available_without_path(isolated_manim_tree, installation) -> None:
    binary = isolated_manim_tree[installation]
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)

    assert manim.shutil.which("manim") is None
    assert manim.manim_bin() == str(binary)
    assert _manim_capability() is True


def test_missing_manim_is_unavailable(isolated_manim_tree) -> None:
    assert manim.manim_bin() is None
    assert _manim_capability() is False


def test_nonexecutable_managed_manim_is_unavailable(isolated_manim_tree) -> None:
    for binary in isolated_manim_tree:
        binary.parent.mkdir(parents=True)
        binary.write_text("not executable\n", encoding="utf-8")
        binary.chmod(0o644)

    assert manim.manim_bin() is None
    assert _manim_capability() is False
