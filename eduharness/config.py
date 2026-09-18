"""Runtime configuration for EduHarness."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv(usecwd=True))
except ImportError:
    def find_dotenv(*args, **kwargs):  # type: ignore[misc]
        """Small fallback for the API-only install when python-dotenv is absent."""
        start = Path.cwd() if kwargs.get("usecwd") else Path(__file__).resolve().parent
        for parent in (start, *start.parents):
            candidate = parent / ".env"
            if candidate.is_file():
                return str(candidate)
        return ""

    def load_dotenv(dotenv_path=None, *args, **kwargs):  # type: ignore[misc]
        path = Path(dotenv_path or find_dotenv(usecwd=True))
        if not path.is_file():
            return False
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if key.startswith("export "):
                key = key[7:].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ.setdefault(key, value)
        return True

from .schema import HarnessRequest


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


@dataclass
class ModelConfig:
    text: str = "gpt-5"
    vision: str = "gpt-5"
    image: str = "gpt-image-2"
    image_prompt: str = "gpt-4o"
    tts: str = "gpt-4o-mini-tts"
    # Reasoning effort for gpt-5 family (minimal | low | medium | high).
    reasoning_effort: str = "medium"
    # Upper bound on completion tokens for gpt-5 (reasoning tokens count too).
    max_completion_tokens: int = 16000
    # Text+vision and image+TTS may live behind different endpoints/keys (e.g. a
    # company proxy that only relays chat). Empty = use OPENAI_BASE_URL / OPENAI_API_KEY.
    text_base_url: str = ""
    text_api_key: str = ""
    media_base_url: str = ""
    media_api_key: str = ""


@dataclass
class Config:
    request: HarnessRequest
    run_dir: Path
    api_key: str = ""
    models: ModelConfig = field(default_factory=ModelConfig)
    max_review_rounds: int = 3
    # Reviewer passes a scene when score >= pass_score AND no blocking issues.
    review_pass_score: float = 7.0
    # Uniformly sampled frames per video for the VLM (guard-flagged frames are added).
    frames_per_video: int = 5
    # Review payload size. Relays that choke on large multi-image requests want
    # fewer/smaller frames and a lower detail level.
    frame_width: int = 1280
    vision_detail: str = "high"
    parallel: int = 4
    manim_quality: str = "l"  # manim -ql
    manim_timeout: int = 360
    manim_container_image: str | None = None
    enable_narration: bool = True
    enable_image: bool = True
    voice: str = "alloy"
    repo_root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[1])

    @classmethod
    def from_env(
        cls,
        request: HarnessRequest,
        run_dir: str | Path | None = None,
        *,
        require_api_key: bool = True,
    ) -> "Config":
        load_dotenv(find_dotenv(usecwd=True))
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        text_key = os.environ.get("EDUHARNESS_TEXT_API_KEY", "").strip() or key
        media_key = os.environ.get("EDUHARNESS_MEDIA_API_KEY", "").strip() or key
        if require_api_key and not text_key:
            raise RuntimeError("OPENAI_API_KEY (or EDUHARNESS_TEXT_API_KEY) is required")
        enable_image = request.enable_image
        enable_narration = request.enable_narration
        if not media_key and (enable_image or enable_narration):
            print("  [config] no media API key (EDUHARNESS_MEDIA_API_KEY / OPENAI_API_KEY): "
                  "image scenes and narration disabled", flush=True)
            enable_image = False
            enable_narration = False
        root = Path(__file__).resolve().parents[1]
        slug = _slug(request.request_id or request.topic)
        out = Path(run_dir) if run_dir else root / "runs" / slug
        models = ModelConfig(
            text=os.environ.get("EDUHARNESS_TEXT_MODEL", "gpt-5"),
            vision=os.environ.get("EDUHARNESS_VISION_MODEL", "gpt-5"),
            image=os.environ.get("EDUHARNESS_IMAGE_MODEL", "gpt-image-2"),
            image_prompt=os.environ.get("EDUHARNESS_IMAGE_PROMPT_MODEL", "gpt-4o"),
            tts=os.environ.get("EDUHARNESS_TTS_MODEL", "gpt-4o-mini-tts"),
            reasoning_effort=os.environ.get("EDUHARNESS_REASONING_EFFORT", "medium"),
            max_completion_tokens=_env_int("EDUHARNESS_MAX_COMPLETION_TOKENS", 16000),
            text_base_url=os.environ.get("EDUHARNESS_TEXT_BASE_URL", "").strip(),
            text_api_key=text_key,
            media_base_url=os.environ.get("EDUHARNESS_MEDIA_BASE_URL", "").strip(),
            media_api_key=media_key,
        )
        return cls(
            request=request,
            api_key=text_key,
            run_dir=out,
            models=models,
            max_review_rounds=request.max_review_rounds,
            review_pass_score=_env_float("EDUHARNESS_PASS_SCORE", 7.0),
            frames_per_video=_env_int("EDUHARNESS_FRAMES_PER_VIDEO", 5),
            frame_width=_env_int("EDUHARNESS_FRAME_WIDTH", 1280),
            vision_detail=os.environ.get("EDUHARNESS_VISION_DETAIL", "high"),
            parallel=_env_int("EDUHARNESS_PARALLEL", request.parallel),
            manim_quality=os.environ.get("EDUHARNESS_MANIM_QUALITY", "l"),
            manim_timeout=_env_int("EDUHARNESS_MANIM_TIMEOUT", 360),
            manim_container_image=os.environ.get("EDUHARNESS_MANIM_CONTAINER_IMAGE") or None,
            enable_narration=enable_narration,
            enable_image=enable_image,
            voice=request.voice,
        )

    def ensure_dirs(self) -> None:
        for sub in (
            "",
            "blueprint",
            "work",
            "media",
            "interactive",
            "frames",
            "debug",
            "bundle",
        ):
            (self.run_dir / sub).mkdir(parents=True, exist_ok=True)

    @property
    def blueprint_path(self) -> Path:
        return self.run_dir / "blueprint" / "lesson_blueprint.json"

    @property
    def style_path(self) -> Path:
        return self.run_dir / "blueprint" / "style_config.json"

    @property
    def manifest_path(self) -> Path:
        return self.run_dir / "bundle" / "manifest.json"

    @property
    def prepared_path(self) -> Path:
        return self.run_dir / "prepared_scenes.json"

    @property
    def rendered_path(self) -> Path:
        return self.run_dir / "rendered_scenes.json"

    @property
    def usage_path(self) -> Path:
        return self.run_dir / "usage.json"

    @property
    def bundle_dir(self) -> Path:
        return self.run_dir / "bundle"


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower()).strip("_")
    return (s or "run")[:64]
