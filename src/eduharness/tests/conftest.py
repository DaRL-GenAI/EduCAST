from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from eduharness.schema import RepairOp
from eduharness.stage2.media import ffmpeg_available, ffmpeg_bin


class FakeProvider:
    """Offline provider that honours the requested pydantic schema.

    `verdict` controls the fake reviewer: a dict of _ReviewOut fields.
    """

    def __init__(self, verdict: dict | None = None, construct_body: str | None = None):
        self.verdict = verdict or {"score": 9, "brief_adherence": 9}
        self.construct_body = construct_body
        self.calls: list[str] = []
        self.tts_calls = 0

    def chat(self, prompt, **kwargs):
        self.calls.append("chat")
        return "ok"

    def chat_json(self, prompt, schema, **kwargs):
        self.calls.append(f"chat_json:{schema.__name__}")
        fields = schema.model_fields
        if "construct_body" in fields:
            return schema(construct_body=self.construct_body or "t = heading('Hi')\nself.play(Write(t))\nself.wait(0.5)")
        if "beat" in fields:
            return schema(beat="bullets", title="Title", bullets=["one", "two"])
        if "parameters" in fields and "template" in fields:
            return schema(template="multiple_choice", parameters={
                "question": "Q?", "choices": ["A", "B", "C"], "correct_index": 1, "explanation": "because",
            }, instruction="Pick one")
        if "scenes" in fields:
            raise AssertionError("planner not faked")
        return schema(**self.verdict)

    def vision(self, prompt, image_paths, **kwargs):
        self.calls.append("vision")
        return "No hard defects."

    def vision_json(self, prompt, image_paths, schema, **kwargs):
        self.calls.append(f"vision_json:{schema.__name__}")
        data = dict(self.verdict)
        if "ops" in data:
            data["ops"] = [RepairOp(**o) if isinstance(o, dict) else o for o in data["ops"]]
        return schema(**data)

    def image(self, prompt, out_path, *, size="1536x1024"):
        self.calls.append("image")
        Image.new("RGB", (300, 200), "#112233").save(out_path)
        return out_path

    def tts(self, text, out_path, *, voice="alloy"):
        self.calls.append("tts")
        self.tts_calls += 1
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [ffmpeg_bin(), "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "1.5",
             "-q:a", "9", str(out_path)],
            check=True, capture_output=True,
        )
        return out_path


@pytest.fixture
def fake_provider():
    return FakeProvider()


@pytest.fixture
def ffmpeg():
    if not ffmpeg_available():
        pytest.skip("ffmpeg is unavailable")
    return True


def make_video(path: Path, seconds: float = 2.0, color: str = "black") -> Path:
    subprocess.run(
        [ffmpeg_bin(), "-y", "-f", "lavfi", "-i", f"color=c={color}:s=640x360:d={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True,
    )
    return path


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))
