"""Backend-independent durable case-store contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from quantforge.audit import AuditLog
from quantforge.domain.models import AuditEvent, TribunalCase
from quantforge.evidence.bundle import EvidenceBundle
from quantforge.evidence.graph import ClaimGraph
from quantforge.evidence.ledger import EvidenceLedger


@dataclass(frozen=True)
class StoreInspection:
    backend: str
    schema_version: int
    case_count: int
    event_count: int
    bundle_count: int
    export_count: int
    integrity: str


@dataclass(frozen=True)
class DurableCase:
    case: TribunalCase
    audit_log: AuditLog
    revision: int
    semantic_hash: str
    audit_head_hash: str
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
    def admit_evidence_bundle(
        self,
        bundle: EvidenceBundle,
        event: AuditEvent,
        *,
        expected_revision: int,
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
