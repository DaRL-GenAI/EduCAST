"""Shared Colab setup: OpenAI API key + real-time usage / cost printing."""

from __future__ import annotations

import os
import sys
from getpass import getpass
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = RUNS_DIR.parent.parent


def resolve_runs_dir() -> Path:
    candidates = [
        Path("/content/drive/MyDrive/education_video/baseline/runs"),
        RUNS_DIR,
        Path.cwd() / "baseline" / "runs",
    ]
    for path in candidates:
        if (path / "colab_bootstrap.py").exists():
            return path
    return RUNS_DIR


def resolve_project_root() -> Path:
    return resolve_runs_dir().parent.parent


USAGE_FILE = Path(
    os.getenv(
        "BASELINE_USAGE_FILE",
        str(resolve_project_root() / "baseline" / "api_usage_session.json"),
    )
)


DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")


def _ensure_project_on_path() -> None:
    runs = resolve_runs_dir()
    root = str(resolve_project_root())
    runs_s = str(runs)
    if root not in sys.path:
        sys.path.insert(0, root)
    if runs_s not in sys.path:
        sys.path.insert(0, runs_s)


def ensure_openai_key() -> str:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        key = getpass("OPENAI_API_KEY: ").strip()
    if not key:
        raise SystemExit("Set OPENAI_API_KEY in Colab secrets or enter when prompted.")
    os.environ["OPENAI_API_KEY"] = key
    os.environ.setdefault("OPENAI_MODEL", DEFAULT_MODEL)
    return key


def setup_api_tracking(usage_file: Path | None = None) -> None:
    _ensure_project_on_path()
    from api_usage_tracker import install_openai_usage_tracker

    path = usage_file or USAGE_FILE
    os.environ["BASELINE_USAGE_FILE"] = str(path)
    install_openai_usage_tracker(path)


def print_api_usage(label: str = "") -> None:
    _ensure_project_on_path()
    from api_usage_tracker import load_usage_file

    usage = load_usage_file(USAGE_FILE)
    prefix = f"[{label}] " if label else ""
    if not usage:
        print(f"{prefix}[usage] no data yet", flush=True)
        return
    cost = float(usage.get("estimated_cost_usd", 0) or 0)
    tokens = int(usage.get("total_tokens", 0) or 0)
    requests = int(usage.get("requests", 0) or 0)
    print(
        f"{prefix}[usage] est. ${cost:.4f} | tokens {tokens:,} "
        f"(in {int(usage.get('prompt_tokens', 0)):,} / out {int(usage.get('completion_tokens', 0)):,}) "
        f"| API calls {requests}",
        flush=True,
    )


def openai_client():
    """Return an OpenAI client using the official API (tracked if setup_api_tracking ran)."""
    from openai import OpenAI

    ensure_openai_key()
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def openai_model() -> str:
    ensure_openai_key()
    return os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)
