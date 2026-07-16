"""Defensive JSON input/output with duplicate-key, size, depth, and path controls."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

from quantforge.serialization.canonical import canonical_json

MAX_JSON_BYTES = 2_000_000
MAX_JSON_DEPTH = 64


def reject_symlink_components(path: Path) -> None:
    """Reject any existing symlink in a path without resolving through it."""

    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ValueError("path may not traverse a symlink")


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

    reject_symlink_components(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("input must be a regular non-symlink file")
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError("JSON input exceeds size limit")
    raw = path.read_text(encoding="utf-8")
    return safe_parse_json(raw, max_bytes=max_bytes)


def safe_parse_json(raw: str, *, max_bytes: int = MAX_JSON_BYTES) -> Any:
    """Parse JSON with the same ambiguity and resource controls used for files."""

    if len(raw.encode("utf-8")) > max_bytes:
        raise ValueError("JSON input exceeds size limit")
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

    safe_write_text(path, canonical_json(value) + "\n")


def safe_write_text(path: Path, value: str) -> None:
    """Atomically write a private UTF-8 file using an unpredictable same-directory temporary."""

    reject_symlink_components(path.parent)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    reject_symlink_components(path)
    if path.exists() and path.is_symlink():
        raise ValueError("refusing to replace a symlink")
    if path.parent.is_symlink():
        raise ValueError("refusing to write through a symlink directory")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        # mkstemp creates a private, exclusively opened file on every supported platform.
        # Retain explicit descriptor hardening where the POSIX API is available; Windows
        # protects the file through its inherited ACL and does not expose os.fchmod.
        fchmod = getattr(os, "fchmod", None)
        if fchmod is not None:
            fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        with suppress(OSError):
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise
