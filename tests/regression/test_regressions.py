from __future__ import annotations

import os
from pathlib import Path

import pytest

from quantforge.serialization.canonical import canonical_sha256
from quantforge.serialization.safe_json import safe_load_json, safe_write_json
from quantforge.workflow.demo import run_demo


def test_named_recursive_json_schema_constructs() -> None:
    result = run_demo("provisional")
    assert result.case.constitution is not None


def test_demo_identity_regression() -> None:
    first = run_demo("provisional")
    second = run_demo("provisional")
    assert canonical_sha256(first.case) == canonical_sha256(second.case)
    assert canonical_sha256(first.audit_log.events) == canonical_sha256(second.audit_log.events)


def test_atomic_json_write_supports_platforms_without_fchmod(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delattr(os, "fchmod", raising=False)
    target = tmp_path / "portable.json"

    safe_write_json(target, {"platform": "portable"})

    assert safe_load_json(target) == {"platform": "portable"}
    assert not list(tmp_path.glob(f".{target.name}.*"))
