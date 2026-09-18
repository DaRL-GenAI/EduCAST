"""Shared Colab session helpers — env paths + API key across notebooks."""

from __future__ import annotations

import json
import os
import sys
from getpass import getpass
from pathlib import Path

ENV_PATH = Path("/content/eduharness_colab_env.json")
# Colab Secret names to try, in order. Override: EDUHARNESS_COLAB_SECRET=your_name
DEFAULT_SECRET_NAMES = ("openai", "OPENAI_API_KEY", "OPENAI_KEY")


def _secret_names() -> tuple[str, ...]:
    override = os.environ.get("EDUHARNESS_COLAB_SECRET", "").strip()
    if override:
        return (override, *DEFAULT_SECRET_NAMES)
    return DEFAULT_SECRET_NAMES


def ensure_api_key(*, prompt: bool = True) -> str:
    """Colab kernels do not share os.environ; reload key every notebook."""
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    try:
        from google.colab import userdata  # type: ignore

        for name in _secret_names():
            try:
                key = userdata.get(name).strip()
            except Exception:
                continue
            if key:
                os.environ["OPENAI_API_KEY"] = key
                return key
    except Exception:
        pass
    if prompt:
        key = getpass("OPENAI_API_KEY: ").strip()
        if key:
            os.environ["OPENAI_API_KEY"] = key
            return key
    raise RuntimeError(
        "OPENAI_API_KEY is required. Add a Colab Secret named 'openai' "
        "(or OPENAI_API_KEY) with Notebook access enabled, or enter it when prompted."
    )


def load_session(*, require_env_file: bool = True) -> dict[str, str]:
    if require_env_file and not ENV_PATH.is_file():
        raise FileNotFoundError(
            f"{ENV_PATH} not found. Run notebooks/01_colab_setup.ipynb first."
        )
    session = json.loads(ENV_PATH.read_text(encoding="utf-8")) if ENV_PATH.is_file() else {}
    repo = Path(session.get("REPO", "/content"))
    os.chdir(repo)
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    os.environ.setdefault("EDUHARNESS_TEXT_MODEL", "gpt-5")
    os.environ.setdefault("EDUHARNESS_VISION_MODEL", "gpt-5")
    os.environ.setdefault("OPENAI_BASE_URL", "https://api.openai.com/v1")
    return session
