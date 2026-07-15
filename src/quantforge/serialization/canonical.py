"""Deterministic JSON serialization used for scientific and audit identities."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel

MAX_DECIMAL_DIGITS = 1_000
MAX_DECIMAL_ADJUSTED_EXPONENT = 1_000


def canonical_decimal(value: Decimal) -> str:
    """Return a bounded, exponent-free decimal identity with one representation for zero."""

    if not value.is_finite():
        raise ValueError("non-finite decimals are forbidden")
    if value.is_zero():
        return "0"
    sign, digits, _ = value.as_tuple()
    if len(digits) > MAX_DECIMAL_DIGITS or abs(value.adjusted()) > MAX_DECIMAL_ADJUSTED_EXPONENT:
        raise ValueError("decimal exceeds canonical magnitude limits")
    normalized = format(value, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    if sign and not normalized.startswith("-"):
        normalized = f"-{normalized}"
    return normalized


def _normalize(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _normalize(value.model_dump(mode="python", exclude_none=False))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("canonical timestamps must be timezone-aware")
        utc = value.astimezone(UTC)
        return utc.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return canonical_decimal(value)
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("canonical JSON object keys must be strings")
        normalized_items: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized_items:
                raise ValueError("canonical Unicode normalization creates a duplicate key")
            normalized_items[normalized_key] = _normalize(item)
        return {key: normalized_items[key] for key in sorted(normalized_items)}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if value is None or isinstance(value, (int, bool)):
        return value
    if isinstance(value, float):
        raise TypeError("floats are forbidden in canonical policy and identity data")
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Return compact UTF-8-safe JSON with stable keys and explicit scalar handling."""

    return json.dumps(
        _normalize(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_sha256(value: Any) -> str:
    """Return the SHA-256 digest of the canonical UTF-8 JSON representation."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
