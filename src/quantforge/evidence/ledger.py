"""In-memory append-only evidence ledger with reference and numeric-fact validation."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from quantforge.domain.models import (
    EvidenceObject,
    EvidenceReference,
    Identifier,
    StrictModel,
    ValidationStatus,
)


class EvidenceLedgerSnapshot(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    case_id: Identifier
    constitution_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence: tuple[EvidenceObject, ...]

    @model_validator(mode="after")
    def unique_and_bound(self) -> Self:
        identifiers = [item.evidence_id for item in self.evidence]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("evidence ledger contains duplicate identifiers")
        if any(item.constitution_hash != self.constitution_hash for item in self.evidence):
            raise ValueError("evidence ledger contains a foreign constitution hash")
        return self


class EvidenceLedger:
    """Mutation is restricted to validated append; existing objects are never replaced."""

    def __init__(self, *, case_id: str, constitution_hash: str, claim_ids: set[str]) -> None:
        self._case_id = case_id
        self._constitution_hash = constitution_hash
        self._claim_ids = frozenset(claim_ids)
        self._items: list[EvidenceObject] = []
        self._by_id: dict[str, EvidenceObject] = {}

    def append(self, evidence: EvidenceObject) -> None:
        if evidence.evidence_id in self._by_id:
            raise ValueError("evidence identifiers are append-only and unique")
        if evidence.constitution_hash != self._constitution_hash:
            raise ValueError("evidence is not bound to the locked constitution")
        if not set(evidence.claim_ids).issubset(self._claim_ids):
            raise ValueError("evidence cites an unknown claim")
        self._items.append(evidence)
        self._by_id[evidence.evidence_id] = evidence

    def get(self, evidence_id: str) -> EvidenceObject:
        try:
            return self._by_id[evidence_id]
        except KeyError as error:
            raise ValueError(f"unknown evidence reference: {evidence_id}") from error

    def validate_reference(
        self, reference: EvidenceReference, *, require_validated: bool = True
    ) -> EvidenceObject:
        evidence = self.get(reference.evidence_id)
        if require_validated and evidence.validation_status is not ValidationStatus.VALIDATED:
            raise ValueError("reviewers may cite numerical facts only from validated evidence")
        facts = {fact.fact_id for fact in evidence.numeric_facts}
        missing = set(reference.numeric_fact_ids).difference(facts)
        if missing:
            raise ValueError(f"unknown numeric fact references: {sorted(missing)}")
        return evidence

    def validate_references(self, references: tuple[EvidenceReference, ...]) -> None:
        for reference in references:
            self.validate_reference(reference)

    def snapshot(self) -> EvidenceLedgerSnapshot:
        return EvidenceLedgerSnapshot(
            case_id=self._case_id,
            constitution_hash=self._constitution_hash,
            evidence=tuple(self._items),
        )

    @classmethod
    def from_snapshot(
        cls, snapshot: EvidenceLedgerSnapshot, *, claim_ids: set[str]
    ) -> EvidenceLedger:
        ledger = cls(
            case_id=snapshot.case_id,
            constitution_hash=snapshot.constitution_hash,
            claim_ids=claim_ids,
        )
        for evidence in snapshot.evidence:
            ledger.append(evidence)
        return ledger
