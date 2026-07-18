"""Backend-independent durable case-store contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import Field, model_validator

from quantforge.audit import AuditLog
from quantforge.domain.models import (
    AuditEvent,
    Identifier,
    RoleName,
    Sha256,
    StrictModel,
    Timestamp,
    TribunalCase,
)
from quantforge.engine.trust import _TrustedAdmissionCapability
from quantforge.evidence.bundle import EvidenceBundle
from quantforge.evidence.graph import ClaimGraph
from quantforge.evidence.ledger import EvidenceLedger
from quantforge.roles.contracts import (
    ProviderAttemptObservation,
    ProviderRequestProvenance,
    ProviderResultAny,
    ProviderTransportOutcome,
    RoleAction,
)


@dataclass(frozen=True)
class StoreInspection:
    backend: str
    schema_version: int
    case_count: int
    event_count: int
    bundle_count: int
    export_count: int
    integrity: str
    provider_invocation_count: int = 0


@dataclass(frozen=True)
class DurableCase:
    case: TribunalCase
    audit_log: AuditLog
    revision: int
    semantic_hash: str
    audit_head_hash: str
    graph_revision: int | None
    graph_hash: str | None
    evidence_ledger: EvidenceLedger | None
    claim_graph: ClaimGraph | None


@dataclass(frozen=True)
class ExportRecord:
    export_id: str
    revision: int
    parent_manifest_hash: str
    manifest_json: str
    manifest_hash: str
    artifact_hashes: tuple[tuple[str, str], ...]


class ProviderInvocationStatus(StrEnum):
    ACCEPTED = "accepted"
    FAILED = "failed"


class ProviderInvocationRecord(StrictModel):
    """One bounded provider transaction; retries remain observations inside one record."""

    invocation_id: Identifier
    status: ProviderInvocationStatus
    case_id: Identifier
    case_revision: int = Field(ge=1, le=10_000)
    role: RoleName
    action: RoleAction
    request_semantic_sha256: Sha256
    request_provenance: ProviderRequestProvenance
    attempts: tuple[ProviderAttemptObservation, ...] = Field(min_length=1, max_length=3)
    accepted_result: ProviderResultAny | None = None
    failure_outcome: ProviderTransportOutcome | None = None
    recorded_at: Timestamp

    @model_validator(mode="after")
    def accepted_or_failed_is_exclusive(self) -> ProviderInvocationRecord:
        if [attempt.attempt_index for attempt in self.attempts] != list(range(len(self.attempts))):
            raise ValueError("provider invocation attempts must be consecutive")
        request_expected = (
            (self.request_provenance.case_id, self.case_id, "request case"),
            (self.request_provenance.case_revision, self.case_revision, "request revision"),
            (self.request_provenance.role, self.role, "request role"),
            (self.request_provenance.action, self.action, "request action"),
            (
                self.request_provenance.canonical_request_sha256,
                self.request_semantic_sha256,
                "request identity",
            ),
        )
        for actual, required, label in request_expected:
            if actual != required:
                raise ValueError(f"provider invocation has a mismatched {label}")
        if self.status is ProviderInvocationStatus.ACCEPTED:
            if self.accepted_result is None or self.failure_outcome is not None:
                raise ValueError("accepted provider invocation requires exactly one result")
            semantic = self.accepted_result.semantic_provenance
            expected = (
                (semantic.case_id, self.case_id, "case"),
                (semantic.case_revision, self.case_revision, "revision"),
                (semantic.role, self.role, "role"),
                (semantic.action, self.action, "action"),
                (
                    semantic.canonical_request_sha256,
                    self.request_semantic_sha256,
                    "request",
                ),
                (
                    self.accepted_result.observational_provenance.attempts,
                    self.attempts,
                    "attempt inventory",
                ),
                (
                    semantic.provider_contract_name,
                    self.request_provenance.provider_contract_name,
                    "provider contract name",
                ),
                (
                    semantic.provider_contract_version,
                    self.request_provenance.provider_contract_version,
                    "provider contract version",
                ),
                (
                    semantic.provider_identity,
                    self.request_provenance.provider_identity,
                    "provider identity",
                ),
                (
                    semantic.endpoint_class,
                    self.request_provenance.endpoint_class,
                    "endpoint class",
                ),
                (semantic.sdk_version, self.request_provenance.sdk_version, "SDK version"),
                (
                    semantic.requested_model,
                    self.request_provenance.requested_model,
                    "requested model",
                ),
                (
                    semantic.prompt_template_id,
                    self.request_provenance.prompt_template_id,
                    "prompt identity",
                ),
                (
                    semantic.prompt_template_version,
                    self.request_provenance.prompt_template_version,
                    "prompt version",
                ),
                (
                    semantic.prompt_template_sha256,
                    self.request_provenance.prompt_template_sha256,
                    "prompt hash",
                ),
                (
                    semantic.structured_output_schema_id,
                    self.request_provenance.structured_output_schema_id,
                    "schema identity",
                ),
                (
                    semantic.structured_output_schema_version,
                    self.request_provenance.structured_output_schema_version,
                    "schema version",
                ),
                (
                    semantic.structured_output_schema_sha256,
                    self.request_provenance.structured_output_schema_sha256,
                    "schema hash",
                ),
                (
                    semantic.validation_policy_id,
                    self.request_provenance.validation_policy_id,
                    "policy identity",
                ),
                (
                    semantic.validation_policy_version,
                    self.request_provenance.validation_policy_version,
                    "policy version",
                ),
                (
                    semantic.validation_policy_sha256,
                    self.request_provenance.validation_policy_sha256,
                    "policy hash",
                ),
                (
                    semantic.retry_policy_id,
                    self.request_provenance.retry_policy_id,
                    "retry policy",
                ),
                (
                    semantic.retry_policy_version,
                    self.request_provenance.retry_policy_version,
                    "retry policy version",
                ),
                (
                    semantic.role_context_sha256,
                    self.request_provenance.role_context_sha256,
                    "role context",
                ),
                (
                    semantic.constitution_identity,
                    self.request_provenance.constitution_identity,
                    "constitution identity",
                ),
                (
                    semantic.amendment_chain_identity,
                    self.request_provenance.amendment_chain_identity,
                    "amendment-chain identity",
                ),
                (
                    semantic.evidence_references,
                    self.request_provenance.evidence_references,
                    "evidence references",
                ),
                (
                    semantic.context_item_identities,
                    self.request_provenance.context_item_identities,
                    "context item identities",
                ),
            )
            for observed, expected_value, label in expected:
                if observed != expected_value:
                    raise ValueError(f"provider invocation has a mismatched {label}")
            if self.attempts[-1].outcome is not ProviderTransportOutcome.ACCEPTED:
                raise ValueError("accepted invocation lacks an accepted terminal attempt")
        else:
            if self.accepted_result is not None or self.failure_outcome is None:
                raise ValueError("failed provider invocation requires exactly one failure outcome")
            if self.failure_outcome is ProviderTransportOutcome.ACCEPTED:
                raise ValueError("failed provider invocation cannot use an accepted outcome")
            if self.attempts[-1].outcome is not self.failure_outcome:
                raise ValueError("failed invocation outcome does not match its terminal attempt")
        return self


class CaseStore(ABC):
    """Explicit persistence interface; domain authority remains outside the backend."""

    @property
    @abstractmethod
    def path(self) -> Path:
        raise NotImplementedError

    @abstractmethod
    def initialize(self) -> StoreInspection:
        raise NotImplementedError

    @abstractmethod
    def inspect(self) -> StoreInspection:
        raise NotImplementedError

    @abstractmethod
    def migrate(self, *, dry_run: bool = False) -> StoreInspection:
        raise NotImplementedError

    @abstractmethod
    def create_case(self, case: TribunalCase, event: AuditEvent) -> int:
        raise NotImplementedError

    @abstractmethod
    def append_event(self, event: AuditEvent, *, expected_revision: int) -> int:
        raise NotImplementedError

    @abstractmethod
    def record_provider_invocation(
        self,
        record: ProviderInvocationRecord,
        event: AuditEvent | None,
        *,
        expected_revision: int,
        final_claim_graph: ClaimGraph | None = None,
    ) -> int:
        raise NotImplementedError

    @abstractmethod
    def find_accepted_provider_invocation(
        self,
        case_id: str,
        *,
        case_revision: int,
        action: RoleAction,
    ) -> ProviderInvocationRecord | None:
        raise NotImplementedError

    @abstractmethod
    def list_provider_invocations(self, case_id: str) -> tuple[ProviderInvocationRecord, ...]:
        raise NotImplementedError

    @abstractmethod
    def admit_evidence_bundle(
        self,
        bundle: EvidenceBundle,
        event: AuditEvent,
        *,
        expected_revision: int,
        capability: _TrustedAdmissionCapability | None = None,
    ) -> int:
        raise NotImplementedError

    @abstractmethod
    def save_claim_graph(self, case_id: str, graph: ClaimGraph, *, expected_revision: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_evidence_bundles(self, case_id: str) -> tuple[EvidenceBundle, ...]:
        raise NotImplementedError

    @abstractmethod
    def find_export(self, case_id: str, export_id: str) -> ExportRecord | None:
        raise NotImplementedError

    @abstractmethod
    def latest_export(self, case_id: str) -> ExportRecord | None:
        raise NotImplementedError

    @abstractmethod
    def record_export(
        self,
        case_id: str,
        record: ExportRecord,
        *,
        expected_revision: int,
        created_at: datetime,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def reconstruct(self, case_id: str, *, require_complete: bool = False) -> DurableCase:
        raise NotImplementedError

    @abstractmethod
    def verify(self) -> StoreInspection:
        raise NotImplementedError
