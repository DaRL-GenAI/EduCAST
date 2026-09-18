from __future__ import annotations

import pytest

from eduharness.stage3.captions import (
    build_caption_cues,
    caption_chunks,
    cues_as_dicts,
    estimate_duration,
    render_webvtt,
    write_webvtt,
)


def test_cues_are_readable_monotonic_and_span_audio() -> None:
    narration = (
        "Torque depends on force and distance. "
        "Move the same force farther from the pivot, and the turning effect increases. "
        "That is why a longer wrench feels easier."
    )
    cues = build_caption_cues(narration, 12.5, max_units=58)

    assert len(cues) >= 3
    assert cues[0].start == 0
    assert cues[-1].end == 12.5
    assert all(cue.start < cue.end for cue in cues)
    assert all(left.end == right.start for left, right in zip(cues, cues[1:]))
    assert all(len(cue.text) <= 58 for cue in cues)  # ASCII has one display unit per char
    assert cues_as_dicts(cues)[0] == {"start": 0.0, "end": cues[0].end, "text": cues[0].text}


def test_cjk_narration_splits_without_spaces_and_preserves_text() -> None:
    narration = (
        "\u529b\u77e9\u7b49\u4e8e\u529b\u4e0e\u529b\u81c2\u7684\u4e58\u79ef\uff0c"
        "\u529b\u81c2\u8d8a\u957f\uff0c\u76f8\u540c\u7684\u529b\u4ea7\u751f\u7684\u8f6c\u52a8\u6548\u679c\u8d8a\u660e\u663e\u3002"
        "\u652f\u70b9\u4f4d\u7f6e\u4e0d\u53d8\u65f6\uff0c\u53ef\u4ee5\u76f4\u63a5\u6bd4\u8f83\u4e24\u4fa7\u7684\u529b\u77e9\u3002"
    )
    chunks = caption_chunks(narration, max_units=32)

    assert len(chunks) >= 3
    assert "".join(chunks) == narration
    assert all(len(chunk) <= 16 for chunk in chunks)  # every glyph here is full-width


def test_decimal_is_not_treated_as_a_sentence_boundary() -> None:
    chunks = caption_chunks("Pi is about 3.14. Use that value in the next step.", max_units=24)
    assert any("3.14" in chunk for chunk in chunks)
    assert not any(chunk.endswith("3.") for chunk in chunks)


def test_missing_duration_gets_a_conservative_estimate() -> None:
    text = "One short sentence. A second sentence adds useful detail."
    cues = build_caption_cues(text, None, max_units=30)
    assert cues[-1].end == estimate_duration(text)
    assert cues[-1].end >= 1.5


def test_webvtt_serialization_and_file_write(tmp_path) -> None:
    cues = build_caption_cues("First idea. Second idea.", 65.25, max_units=12)
    payload = render_webvtt(cues)
    assert payload.startswith("WEBVTT\n\n1\n00:00:00.000 --> ")
    assert "00:01:" in payload
    assert "First idea." in payload

    path = tmp_path / "captions" / "scene.vtt"
    write_webvtt(path, cues)
    assert path.read_text(encoding="utf-8") == payload


def test_empty_text_and_invalid_width() -> None:
    assert build_caption_cues("   ", 8) == []
    with pytest.raises(ValueError, match="at least 12"):
        caption_chunks("text", max_units=4)
