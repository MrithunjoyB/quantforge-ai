from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from quantforge.domain.models import EvidenceReference, ValidationStatus
from quantforge.evidence.ledger import (
    EvidenceLedger,
    EvidenceLedgerSnapshot,
    verify_source_artifact,
)
from quantforge.workflow.demo import run_demo


def _changed(item: Any, **updates: Any) -> Any:
    data = item.model_dump(mode="python")
    data.update(updates)
    return type(item).model_validate(data)


def test_evidence_hash_tampering_is_rejected() -> None:
    item = run_demo("provisional").evidence_ledger.snapshot().evidence[0]
    data = item.model_dump(mode="python")
    data["content"] = {"tampered": True}
    with pytest.raises(ValidationError, match="content hash mismatch"):
        type(item).model_validate(data)


def test_ledger_rejects_duplicate_foreign_and_unknown_claim_evidence() -> None:
    result = run_demo("provisional")
    snapshot = result.evidence_ledger.snapshot()
    item = snapshot.evidence[0]
    ledger = EvidenceLedger(
        case_id=snapshot.case_id,
        experiment_id=snapshot.experiment_id,
        constitution_hash=snapshot.constitution_hash,
        claim_ids={result.case.claim.claim_id},
    )
    ledger.append(item)
    with pytest.raises(ValueError, match="unique"):
        ledger.append(item)
    with pytest.raises(ValueError, match="locked constitution"):
        ledger.append(_changed(item, evidence_id="evidence_foreign", constitution_hash="0" * 64))
    with pytest.raises(ValueError, match="unknown claim"):
        ledger.append(
            _changed(item, evidence_id="evidence_unknown_claim", claim_ids=("claim_unknown",))
        )
    with pytest.raises(ValueError, match="active case"):
        ledger.append(_changed(item, evidence_id="evidence_other_case", case_id="case_other"))
    with pytest.raises(ValueError, match="active experiment"):
        ledger.append(
            _changed(
                item,
                evidence_id="evidence_other_experiment",
                experiment_id="experiment_other",
            )
        )


def test_evidence_reference_validation() -> None:
    result = run_demo("provisional")
    ledger = result.evidence_ledger
    item = ledger.snapshot().evidence[0]
    ledger.validate_reference(
        EvidenceReference(
            evidence_id=item.evidence_id,
            numeric_fact_ids=(item.numeric_facts[0].fact_id,),
        )
    )
    with pytest.raises(ValueError, match="unknown evidence"):
        ledger.validate_reference(EvidenceReference(evidence_id="evidence_missing"))
    with pytest.raises(ValueError, match="unknown numeric fact"):
        ledger.validate_reference(
            EvidenceReference(evidence_id=item.evidence_id, numeric_fact_ids=("fact_missing",))
        )
    pending = _changed(
        item, evidence_id="evidence_pending", validation_status=ValidationStatus.PENDING
    )
    pending_ledger = EvidenceLedger(
        case_id=result.case.case_id,
        experiment_id=item.experiment_id,
        constitution_hash=item.constitution_hash,
        claim_ids={result.case.claim.claim_id},
    )
    pending_ledger.append(pending)
    with pytest.raises(ValueError, match="validated evidence"):
        pending_ledger.validate_reference(EvidenceReference(evidence_id=pending.evidence_id))
    pending_ledger.validate_reference(
        EvidenceReference(evidence_id=pending.evidence_id), require_validated=False
    )


def test_ledger_snapshot_roundtrip_and_snapshot_corruption() -> None:
    result = run_demo("provisional")
    snapshot = result.evidence_ledger.snapshot()
    restored = EvidenceLedger.from_snapshot(snapshot, claim_ids={result.case.claim.claim_id})
    assert restored.snapshot() == snapshot
    with pytest.raises(ValidationError, match="duplicate"):
        EvidenceLedgerSnapshot(
            case_id=snapshot.case_id,
            experiment_id=snapshot.experiment_id,
            constitution_hash=snapshot.constitution_hash,
            evidence=(snapshot.evidence[0], snapshot.evidence[0]),
        )
    foreign = _changed(snapshot.evidence[0], constitution_hash="0" * 64)
    with pytest.raises(ValidationError, match="foreign"):
        EvidenceLedgerSnapshot(
            case_id=snapshot.case_id,
            experiment_id=snapshot.experiment_id,
            constitution_hash=snapshot.constitution_hash,
            evidence=(foreign,),
        )


def test_unsupported_numerical_text_is_rejected() -> None:
    finding = run_demo("provisional").case.statistical_review
    assert finding is not None
    data = finding.findings[0].model_dump(mode="python")
    data["summary"] = "The effect is 42 basis points"
    with pytest.raises(ValidationError, match="numerical text"):
        type(finding.findings[0]).model_validate(data)


def test_duplicate_and_nonfinite_numeric_facts_are_rejected() -> None:
    item = run_demo("provisional").evidence_ledger.snapshot().evidence[0]
    data = item.model_dump(mode="python")
    data["numeric_facts"] = (item.numeric_facts[0], item.numeric_facts[0])
    with pytest.raises(ValidationError, match="duplicate numeric fact"):
        type(item).model_validate(data)
    fact_data = item.numeric_facts[0].model_dump(mode="python")
    fact_data["value"] = Decimal("NaN")
    with pytest.raises(ValidationError, match="finite"):
        type(item.numeric_facts[0]).model_validate(fact_data)


def test_numeric_facts_and_units_are_bound_to_hashed_content() -> None:
    item = run_demo("provisional").evidence_ledger.snapshot().evidence[0]
    fact = item.numeric_facts[0]
    changed_fact = type(fact).model_validate(
        {**fact.model_dump(mode="python"), "value": Decimal("999")}
    )
    with pytest.raises(ValidationError, match="numeric facts"):
        _changed(item, numeric_facts=(changed_fact,))
    with pytest.raises(ValidationError, match="units"):
        _changed(item, units=())
    with pytest.raises(ValidationError, match="literal_error"):
        type(fact).model_validate({**fact.model_dump(mode="python"), "unit": "fortnights"})
    with pytest.raises(ValidationError, match="JSON pointer"):
        _changed(item, structured_location="/evidence/../secret")


@pytest.mark.parametrize("numeric_text", ["Effect 1e3", "Effect NaN", "Effect Infinity"])
def test_numerical_narrative_edge_forms_are_rejected(numeric_text: str) -> None:
    finding = run_demo("provisional").case.statistical_review
    assert finding is not None
    item = finding.findings[0]
    with pytest.raises(ValidationError, match="numerical text"):
        type(item).model_validate({**item.model_dump(mode="python"), "summary": numeric_text})


def test_source_artifact_existence_hash_and_symlink_controls(tmp_path: Path) -> None:
    item = run_demo("provisional").evidence_ledger.snapshot().evidence[0]
    artifact = tmp_path / "artifact.json"
    artifact.write_text("synthetic", encoding="utf-8")
    local = _changed(
        item,
        source_artifact="artifact.json",
        source_artifact_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
    )
    assert verify_source_artifact(local, tmp_path) == artifact
    with pytest.raises(ValueError, match="bounded regular"):
        verify_source_artifact(_changed(local, source_artifact="missing.json"), tmp_path)
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_source_artifact(_changed(local, source_artifact_sha256="0" * 64), tmp_path)
    link = tmp_path / "linked.json"
    link.symlink_to(artifact)
    with pytest.raises(ValueError, match="symlink"):
        verify_source_artifact(_changed(local, source_artifact="linked.json"), tmp_path)
