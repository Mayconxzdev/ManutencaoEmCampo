"""Configuração central de limites de upload/importação por tipo de arquivo."""
from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any

from app.config import CONFIG_DIR


MB = 1024 * 1024
GB = 1024 * MB

DEFAULT_LIMITS: dict[str, int] = {
    "image": 100 * MB,
    "document": 500 * MB,
    "audio": 500 * MB,
    "video": 2 * GB,
    "other": 500 * MB,
}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".pptx", ".txt", ".csv"}
AUDIO_EXTENSIONS = {".ogg", ".mp3", ".wav", ".m4a", ".webm"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


def limits_path() -> Path:
    return CONFIG_DIR / "file_limits.json"


def category_for_name(file_name: str, mime_type: str | None = None) -> str:
    suffix = Path(file_name).suffix.lower()
    if suffix in IMAGE_EXTENSIONS or (mime_type or "").startswith("image/"):
        return "image"
    if suffix in AUDIO_EXTENSIONS or (mime_type or "").startswith("audio/"):
        return "audio"
    if suffix in VIDEO_EXTENSIONS or (mime_type or "").startswith("video/"):
        return "video"
    if suffix in DOCUMENT_EXTENSIONS:
        return "document"
    return "other"


def load_limits() -> dict[str, int]:
    path = limits_path()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(DEFAULT_LIMITS, indent=2), encoding="utf-8")
        return dict(DEFAULT_LIMITS)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return dict(DEFAULT_LIMITS)
    limits = dict(DEFAULT_LIMITS)
    for key, value in raw.items():
        if key in limits:
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                limits[key] = parsed
    return limits


def get_limit_for_name(file_name: str, mime_type: str | None = None) -> int:
    limits = load_limits()
    return limits.get(category_for_name(file_name, mime_type), limits["other"])


def get_limit_for_path(path: Path, mime_type: str | None = None) -> int:
    guessed = mime_type or mimetypes.guess_type(path.name)[0]
    return get_limit_for_name(path.name, guessed)


def serialize_limits() -> dict[str, Any]:
    limits = load_limits()
    return {
        "bytes": limits,
        "mb": {key: round(value / MB, 2) for key, value in limits.items()},
        "path": str(limits_path()),
    }
