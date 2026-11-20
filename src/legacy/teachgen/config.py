"""Single source of configuration.

The whole point of teachgen is "one OpenAI key + one topic". Everything funnels
through here: the API key comes from the environment, model names have sane
defaults, and all paths hang off one run directory.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ModelConfig:
    """Which concrete models the default OpenAI provider should use."""

    text: str = "gpt-4o"            # planning, content writing, routing
    vision: str = "gpt-4o"          # MLLM reviewer (reads sampled video frames)
    tts: str = "gpt-4o-mini-tts"    # narration synthesis
    transcribe: str = "whisper-1"   # word-level timestamps for A/V alignment
    image: str = "gpt-image-2"      # concept_image renderer


@dataclass
class Config:
    """Top-level run configuration. Construct via `Config.from_env(topic=...)`."""

    topic: str
    audience: str = "general learners"
    provider: str = "openai"        # "openai" (default) | "gemini"
    api_key: str = ""

    models: ModelConfig = field(default_factory=ModelConfig)

    # Feedback loop
    use_feedback: bool = True
    max_outer_rounds: int = 3       # outer loop cap
    score_threshold: float = 8.0   # stop early when overall_score >= this

    # Execution
    parallel: bool = True
    max_workers: int = 6

    # Paths
    run_dir: Path = Path("runs")

    # Where the existing repos live (we adapt, not fork, them)
    repo_root: Path = Path(__file__).resolve().parent.parent

    @classmethod
    def from_env(cls, topic: str, **overrides) -> "Config":
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key and overrides.get("provider", "openai") == "openai":
            raise SystemExit(
                "OPENAI_API_KEY is not set. Export it first:\n"
                "    export OPENAI_API_KEY=sk-..."
            )
        cfg = cls(topic=topic, api_key=api_key, **overrides)  # type: ignore[arg-type]
        cfg.run_dir = Path(cfg.run_dir) / _safe_slug(topic)
        return cfg

    # --- derived paths (created lazily by the pipeline) ---
    @property
    def plan_path(self) -> Path:
        return self.run_dir / "lesson_plan.json"

    @property
    def assets_dir(self) -> Path:
        return self.run_dir / "assets"      # per-segment visuals

    @property
    def audio_dir(self) -> Path:
        return self.run_dir / "audio"       # per-segment narration

    @property
    def video_dir(self) -> Path:
        return self.run_dir / "video"       # draft + final composites

    def ensure_dirs(self) -> None:
        for d in (self.run_dir, self.assets_dir, self.audio_dir, self.video_dir):
            d.mkdir(parents=True, exist_ok=True)


def _safe_slug(text: str, maxlen: int = 60) -> str:
    keep = [c if c.isalnum() else "-" for c in text.strip().lower()]
    slug = "".join(keep).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:maxlen] or "untitled"
