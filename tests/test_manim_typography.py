"""Glyph spacing must scale smoothly and old fallback SVGs must not be reused."""

from pathlib import Path

import pytest

from eduharness.schema import StyleConfig
from eduharness.stage2.adapters import manim as adapter


def test_small_text_retains_glyph_spacing_when_scaled(tmp_path, monkeypatch):
    pytest.importorskip("manim")
    monkeypatch.chdir(tmp_path)
    ns = {}
    exec(adapter.assemble_script("pass", StyleConfig()), ns)
    small = ns["Text"]("effect, torque and distance", font="Inter", font_size=14.904)
    medium = ns["Text"]("effect, torque and distance", font="Inter", font_size=22)
    assert isinstance(small, ns["_TEXT_TYPES"])
    assert small.font_size == pytest.approx(14.904)
    assert small.width / 14.904 == pytest.approx(medium.width / 22)
    small_offsets = [(g.get_center()[0] - small.get_left()[0]) / 14.904 for g in small]
    medium_offsets = [(g.get_center()[0] - medium.get_left()[0]) / 22 for g in medium]
    assert small_offsets == pytest.approx(medium_offsets)
    assert ns["Text"]("default").font_size == pytest.approx(48)
    assert ns["Text"]("explicit dimensions", font_size=14, width=3).width == pytest.approx(3)


def test_font_contents_change_text_cache_namespace(tmp_path, monkeypatch):
    font = tmp_path / "font.ttf"
    monkeypatch.setattr(adapter, "bundled_manim_fonts", lambda _: [font])
    font.write_bytes(b"original font bytes")
    before = adapter.manim_font_cache_key("Example")
    font.write_bytes(b"replacement font bytes")
    after = adapter.manim_font_cache_key("Example")
    assert before != after


def test_text_does_not_reuse_legacy_svg_and_wraps_by_measured_width(tmp_path, monkeypatch):
    manim = pytest.importorskip("manim")
    monkeypatch.chdir(tmp_path)
    text = "The turning effect is called torque, symbol tau."
    with manim.tempconfig({"text_dir": "{media_dir}/texts"}):
        legacy = manim.Text(text, font="Inter", font_size=14.904)
    legacy_path = Path(legacy.file_name)
    legacy_path.write_text("invalid cached font geometry")
    ns = {}
    exec(adapter.assemble_script("pass", StyleConfig()), ns)
    current = ns["Text"](text, font="Inter", font_size=14.904)
    assert Path(current.file_name).parent != legacy_path.parent
    assert legacy_path.read_text() == "invalid cached font geometry"
    wrapped = ns["_wrap_lecture"](text, 3.5)
    assert wrapped.replace("\n", " ") == text
    assert len(wrapped.splitlines()[0]) > 23
    for line in wrapped.splitlines():
        assert ns["label"](line, size=0.69).width <= 3.5
