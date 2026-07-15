from __future__ import annotations

from quantforge.serialization.canonical import canonical_sha256
from quantforge.workflow.demo import run_demo


def test_named_recursive_json_schema_constructs() -> None:
    result = run_demo("provisional")
    assert result.case.constitution is not None


def test_demo_identity_regression() -> None:
    first = run_demo("provisional")
    second = run_demo("provisional")
    assert canonical_sha256(first.case) == canonical_sha256(second.case)
    assert canonical_sha256(first.audit_log.events) == canonical_sha256(second.audit_log.events)
