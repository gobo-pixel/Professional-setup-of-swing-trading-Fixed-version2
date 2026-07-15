"""
Common utility functions.

Rules:
- Generic helpers only
- No trading/business logic
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from core.types import JSONValue, PathLike


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.utcnow()


def ensure_directory(path: PathLike) -> Path:
    """Create a directory if it does not exist."""
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def read_json(path: PathLike) -> JSONValue:
    """Read a JSON file."""
    with Path(path).open("r", encoding="utf-8") as fp:
        return json.load(fp)


def write_json(path: PathLike, data: JSONValue, indent: int = 2) -> None:
    """Write data to a JSON file."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8") as fp:
        json.dump(data, fp, indent=indent, ensure_ascii=False)


def sha256_hash(value: str) -> str:
    """Return SHA-256 hash of a string."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert a value to float."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    """Safely convert a value to int."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
