"""Shared helpers for baseline batch runners."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

WORK_ROOT = Path("/content/drive/MyDrive/education_video")
try:
    import google.colab  # type: ignore  # noqa: F401
except Exception:
    WORK_ROOT = Path("/Users/alyssa/Desktop/education_video")

TOPICS_XLSX = WORK_ROOT / "topics.xlsx"

EXCLUDE_MP4_PARTS = {
    "partial_movie_files",
    "chunks",
    "chunk_analyses",
    "media",
    "images",
    "frames",
    "cache",
    "tmp",
}


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def load_all_topics(xlsx_path: Path | None = None, max_topics: int | None = None) -> list[dict[str, str]]:
    path = xlsx_path or TOPICS_XLSX
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    header = [clean(x) for x in next(rows)]

    out: list[dict[str, str]] = []
    for row_idx, raw in enumerate(rows, start=2):
        item = {header[i]: clean(raw[i]) if i < len(raw) else "" for i in range(len(header))}
        req_id = item.get("Request ID", "")
        topic = item.get("Topic", "")
        persona = item.get("Student Persona", "")
        if not req_id or not topic:
            continue
        if req_id == "Request ID" or topic == "Topic":
            continue
        out.append(
            {
                "row": str(row_idx),
                "request_id": req_id,
                "topic": topic,
                "persona": persona,
            }
        )
        if max_topics is not None and len(out) >= max_topics:
            break
    return out


def safe_name(text: str, max_len: int = 80) -> str:
    out = re.sub(r"[^a-zA-Z0-9._-]+", "_", text).strip("_")
    return out[:max_len] if len(out) > max_len else out


def is_final_mp4(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() != ".mp4":
        return False
    parts = {p.lower() for p in path.parts}
    if parts & EXCLUDE_MP4_PARTS:
        return False
    stem = path.stem.lower()
    if stem.startswith("section") and stem.endswith("scene"):
        return False
    return True


def topic_has_video(output_parent: Path, request_id: str) -> bool:
    if not output_parent.exists():
        return False
    for run_dir in sorted(output_parent.glob("run_*")) + sorted(output_parent.glob("20*")):
        if not run_dir.is_dir():
            continue
        for topic_dir in run_dir.iterdir():
            if not topic_dir.is_dir() or request_id not in topic_dir.name:
                continue
            for mp4 in topic_dir.rglob("*.mp4"):
                if is_final_mp4(mp4):
                    return True
    return False


def pending_topics(output_parent: Path, xlsx_path: Path | None = None) -> list[dict[str, str]]:
    return [t for t in load_all_topics(xlsx_path) if not topic_has_video(output_parent, t["request_id"])]
