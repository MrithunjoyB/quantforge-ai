"""Independent defensive validation of official SDK structured output text."""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence

from pydantic import ValidationError

from quantforge.domain.models import StrictModel
from quantforge.serialization.safe_json import safe_parse_json

MAX_STRUCTURED_COLLECTION_ITEMS = 256


def _validate_unicode(value: object) -> None:
    if isinstance(value, Mapping):
        if len(value) > MAX_STRUCTURED_COLLECTION_ITEMS:
            raise ValueError("structured output object exceeds the item limit")
        for key, item in value.items():
            if not key.isascii():
                raise ValueError("structured output keys must be ASCII schema identifiers")
            _validate_unicode(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > MAX_STRUCTURED_COLLECTION_ITEMS:
            raise ValueError("structured output array exceeds the item limit")
        for item in value:
            _validate_unicode(item)
    elif isinstance(value, str):
        if unicodedata.normalize("NFC", value) != value:
            raise ValueError("structured output contains non-canonical Unicode")
        if any(
            unicodedata.category(character) in {"Cc", "Cf", "Cs", "Co", "Cn"} for character in value
        ):
            raise ValueError("structured output contains a forbidden Unicode code point")


def validate_structured_output[OutputT: StrictModel](
    raw: str,
    output_type: type[OutputT],
    *,
    maximum_response_bytes: int,
) -> OutputT:
    """Reject ambiguous JSON before applying the exact Pydantic domain schema."""

    if raw.startswith("```") or raw.rstrip().endswith("```"):
        raise ValueError("markdown-wrapped pseudo-JSON is forbidden")
    try:
        encoded = raw.encode("utf-8", errors="strict")
    except UnicodeError as error:
        raise ValueError("structured output is not valid Unicode") from error
    if len(encoded) > maximum_response_bytes:
        raise ValueError("structured output exceeds the response byte budget")
    parsed = safe_parse_json(raw, max_bytes=maximum_response_bytes)
    if not isinstance(parsed, dict):
        raise ValueError("structured output must be one JSON object")
    _validate_unicode(parsed)
    try:
        return output_type.model_validate_json(raw, strict=True)
    except ValidationError as error:
        raise ValueError("structured output failed its exact domain schema") from error


__all__ = ["validate_structured_output"]
