"""Defensive JSON input/output with duplicate-key, size, depth, and path controls."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from quantforge.serialization.canonical import canonical_json

MAX_JSON_BYTES = 2_000_000
MAX_JSON_DEPTH = 64


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _depth(value: Any, current: int = 0) -> int:
    if current > MAX_JSON_DEPTH:
        raise ValueError("JSON nesting exceeds safety limit")
    if isinstance(value, dict):
        return max((_depth(item, current + 1) for item in value.values()), default=current)
    if isinstance(value, list):
        return max((_depth(item, current + 1) for item in value), default=current)
    return current


def safe_load_json(path: Path, *, max_bytes: int = MAX_JSON_BYTES) -> Any:
    """Load a bounded UTF-8 JSON file and reject ambiguous or malicious structures."""

    if path.is_symlink() or not path.is_file():
        raise ValueError("input must be a regular non-symlink file")
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError("JSON input exceeds size limit")
    raw = path.read_text(encoding="utf-8")
    return safe_parse_json(raw)


def safe_parse_json(raw: str) -> Any:
    """Parse JSON with the same ambiguity and resource controls used for files."""

    value = json.loads(
        raw,
        object_pairs_hook=_reject_duplicates,
        parse_float=lambda value: (_ for _ in ()).throw(
            ValueError(f"JSON floats are forbidden; use decimal strings: {value}")
        ),
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"non-finite JSON value is forbidden: {value}")
        ),
    )
    _depth(value)
    return value


def safe_write_json(path: Path, value: Any) -> None:
    """Atomically write canonical JSON without following a destination symlink."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.is_symlink():
        raise ValueError("refusing to replace a symlink")
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(canonical_json(value) + "\n", encoding="utf-8")
    os.replace(temporary, path)
