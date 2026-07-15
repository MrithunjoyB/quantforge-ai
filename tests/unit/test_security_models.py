from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from quantforge.domain.models import EvidenceObject, TribunalCase
from quantforge.serialization.canonical import canonical_json
from quantforge.workflow.demo import run_demo


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "../secret",
        "/absolute/artifact",
        "~/.env",
        "folder\\artifact",
        "folder/../artifact",
        "folder//artifact",
    ],
)
def test_unsafe_artifact_references_are_rejected(unsafe_path: str) -> None:
    item = run_demo("provisional").evidence_ledger.snapshot().evidence[0]
    data = item.model_dump(mode="python")
    data["source_artifact"] = unsafe_path
    with pytest.raises(ValidationError, match="artifact path"):
        EvidenceObject.model_validate(data)


def test_unknown_fields_and_schema_versions_are_rejected() -> None:
    case = run_demo("provisional").case
    data: dict[str, Any] = case.model_dump(mode="python")
    data["injected"] = "prompt"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        TribunalCase.model_validate(data)
    data = case.model_dump(mode="python")
    data["schema_version"] = "9.9"
    with pytest.raises(ValidationError, match="literal_error"):
        TribunalCase.model_validate(data)


def test_case_roundtrip_uses_no_floats_or_absolute_paths() -> None:
    payload = canonical_json(run_demo("provisional").case)
    assert "/Users/" not in payload
    assert "OPENAI_API_KEY" not in payload
    restored = TribunalCase.model_validate_json(payload)
    assert restored == run_demo("provisional").case
