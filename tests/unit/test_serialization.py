from __future__ import annotations

import os
import stat
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from quantforge.serialization.canonical import canonical_json, canonical_sha256
from quantforge.serialization.safe_json import safe_load_json, safe_parse_json, safe_write_json


def test_canonical_json_is_stable_and_explicit() -> None:
    left = {"z": Decimal("1.2300"), "a": datetime(2026, 1, 1, tzinfo=UTC)}
    right = {"a": datetime(2026, 1, 1, tzinfo=UTC), "z": Decimal("1.23")}
    assert canonical_json(left) == canonical_json(right)
    assert canonical_sha256(left) == canonical_sha256(right)
    assert '"z":"1.23"' in canonical_json(left)
    assert canonical_json(Decimal("-0")) == canonical_json(Decimal("0")) == '"0"'


def test_canonical_unicode_normalization_is_stable_and_collision_safe() -> None:
    assert canonical_json("e\u0301") == canonical_json("é")
    with pytest.raises(ValueError, match="duplicate key"):
        canonical_json({"e\u0301": True, "é": False})


@pytest.mark.parametrize(
    "value, error",
    [
        (1.0, TypeError),
        (Decimal("NaN"), ValueError),
        ({1: "bad"}, TypeError),
        ({"bad": object()}, TypeError),
        (datetime(2026, 1, 1), ValueError),
    ],
)
def test_canonical_json_rejects_ambiguous_values(value: object, error: type[Exception]) -> None:
    with pytest.raises(error):
        canonical_json(value)


@pytest.mark.parametrize(
    "raw, message",
    [
        ('{"a":1,"a":2}', "duplicate"),
        ('{"a":1.5}', "floats"),
        ('{"a":NaN}', "non-finite"),
    ],
)
def test_safe_parser_rejects_ambiguous_json(raw: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        safe_parse_json(raw)


def test_safe_parser_rejects_excess_depth() -> None:
    raw = "[" * 66 + "null" + "]" * 66
    with pytest.raises(ValueError, match="nesting"):
        safe_parse_json(raw)


def test_safe_parser_applies_size_limit_to_in_memory_input() -> None:
    with pytest.raises(ValueError, match="size"):
        safe_parse_json('"oversized"', max_bytes=2)


def test_safe_json_round_trip_and_file_controls(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "value.json"
    safe_write_json(target, {"ok": True})
    assert safe_load_json(target) == {"ok": True}
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert not list(target.parent.glob(f".{target.name}.*"))
    with pytest.raises(ValueError, match="size"):
        safe_load_json(target, max_bytes=1)
    symlink = tmp_path / "link.json"
    os.symlink(target, symlink)
    with pytest.raises(ValueError, match="symlink"):
        safe_load_json(symlink)
    with pytest.raises(ValueError, match="symlink"):
        safe_write_json(symlink, {"bad": True})
    with pytest.raises(ValueError, match="regular"):
        safe_load_json(tmp_path)
    real_directory = tmp_path / "real"
    real_directory.mkdir()
    linked_directory = tmp_path / "linked_directory"
    linked_directory.symlink_to(real_directory, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        safe_write_json(linked_directory / "escaped.json", {"bad": True})
