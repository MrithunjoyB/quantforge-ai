"""In-process execution authority that cannot be reconstructed from serialized evidence."""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from typing import Final

from quantforge.domain.models import AuditEvent
from quantforge.engine.base import EngineRun
from quantforge.evidence.bundle import EvidenceBundle
from quantforge.serialization.canonical import canonical_sha256

ADAPTER_CONTRACT_VERSION: Final = "cpp-v1-adapter/2.0"
_AUTHORITY: Final = object()


@dataclass(frozen=True)
class TrustedReceiptRecord:
    """Inspectable receipt facts; this record alone grants no admission authority."""

    adapter_contract_version: str
    case_id: str
    workflow_revision: int
    constitution_id: str
    constitution_hash: str
    amendment_chain_hash: str
    repository: str
    release: str
    annotated_tag_object: str
    peeled_target: str
    executable_sha256: str
    configuration_sha256: str
    configuration_semantic_sha256: str
    input_hashes: tuple[tuple[str, str, str, int, str], ...]
    output_hashes: tuple[tuple[str, str, str, int, str], ...]
    validator_executions: tuple[tuple[str, str, str, str], ...]
    invocation_contract_version: str
    repository_snapshot_sha256: str
    validator_source_sha256: str
    run_fingerprint: str


@dataclass(frozen=True)
class TrustedEngineExecution:
    run: EngineRun
    receipt: TrustedExecutionReceipt


def _artifact_hashes(run: EngineRun, *, output: bool) -> tuple[tuple[str, str, str, int, str], ...]:
    semantics = run.output_semantics if output else run.input_semantics
    observations = run.output_observations if output else run.input_observations
    semantic_by_path = {item.path: item for item in semantics}
    return tuple(
        (
            item.path,
            item.byte_sha256,
            semantic_by_path[item.path].semantic_sha256,
            item.size_bytes,
            semantic_by_path[item.path].schema_version,
        )
        for item in observations
    )


def _fingerprint_run(run: EngineRun) -> str:
    return canonical_sha256(
        {
            "configuration_sha256": run.configuration_sha256,
            "engine": run.engine,
            "execution_completed_at": run.execution_completed_at,
            "execution_started_at": run.execution_started_at,
            "input_observations": run.input_observations,
            "input_semantics": run.input_semantics,
            "invocation": run.invocation,
            "numeric_facts": run.numeric_facts,
            "output_observations": run.output_observations,
            "output_semantics": run.output_semantics,
            "stderr_sha256": run.stderr_sha256,
            "stdout_sha256": run.stdout_sha256,
            "validators": run.validators,
        }
    )


def _receipt_record(
    run: EngineRun,
    *,
    case_id: str,
    workflow_revision: int,
    constitution_id: str,
    constitution_hash: str,
    amendment_chain_hash: str,
    configuration_semantic_sha256: str,
    repository_snapshot_sha256: str,
    validator_source_sha256: str,
) -> TrustedReceiptRecord:
    return TrustedReceiptRecord(
        adapter_contract_version=ADAPTER_CONTRACT_VERSION,
        case_id=case_id,
        workflow_revision=workflow_revision,
        constitution_id=constitution_id,
        constitution_hash=constitution_hash,
        amendment_chain_hash=amendment_chain_hash,
        repository=run.engine.repository,
        release=run.engine.release,
        annotated_tag_object=run.engine.annotated_tag_object,
        peeled_target=run.engine.peeled_target,
        executable_sha256=run.engine.executable_sha256,
        configuration_sha256=run.configuration_sha256,
        configuration_semantic_sha256=configuration_semantic_sha256,
        input_hashes=_artifact_hashes(run, output=False),
        output_hashes=_artifact_hashes(run, output=True),
        validator_executions=tuple(
            (item.name, item.contract_version, item.status, item.output_sha256)
            for item in run.validators
        ),
        invocation_contract_version=run.invocation.contract_version,
        repository_snapshot_sha256=repository_snapshot_sha256,
        validator_source_sha256=validator_source_sha256,
        run_fingerprint=_fingerprint_run(run),
    )


class TrustedExecutionReceipt:
    """One-shot code-owned capability; JSON and model data cannot instantiate it."""

    __slots__ = ("_authority", "_consumed", "_lock", "_nonce", "_record")

    def __init__(
        self,
        record: TrustedReceiptRecord,
        *,
        _authority: object | None = None,
    ) -> None:
        if _authority is not _AUTHORITY:
            raise TypeError("trusted execution receipts are issued only by the approved adapter")
        self._authority = _authority
        self._record = record
        self._nonce = secrets.token_bytes(32)
        self._consumed = False
        self._lock = threading.Lock()

    @property
    def record(self) -> TrustedReceiptRecord:
        return self._record

    def _consume(
        self,
        run: EngineRun,
        bundle: EvidenceBundle,
        *,
        configuration_semantic_sha256: str,
        repository_snapshot_sha256: str,
        validator_source_sha256: str,
    ) -> _TrustedAdmissionCapability:
        expected = _receipt_record(
            run,
            case_id=bundle.semantic.case_id,
            workflow_revision=bundle.semantic.workflow_revision,
            constitution_id=bundle.semantic.constitution_id,
            constitution_hash=bundle.semantic.constitution_hash,
            amendment_chain_hash=bundle.semantic.amendment_chain_hash,
            configuration_semantic_sha256=configuration_semantic_sha256,
            repository_snapshot_sha256=repository_snapshot_sha256,
            validator_source_sha256=validator_source_sha256,
        )
        with self._lock:
            if self._authority is not _AUTHORITY or self._consumed:
                raise ValueError(
                    "trusted execution receipt is invalid or has already been consumed"
                )
            if self._record != expected:
                raise ValueError(
                    "trusted execution receipt does not bind this run and case revision"
                )
            semantic = bundle.semantic
            if (
                semantic.engine != run.engine
                or semantic.invocation != run.invocation
                or semantic.configuration_sha256 != run.configuration_sha256
                or semantic.input_artifacts != run.input_semantics
                or semantic.output_artifacts != run.output_semantics
                or semantic.validator_results != run.validators
                or semantic.numeric_facts != run.numeric_facts
                or bundle.observations.input_artifacts != run.input_observations
                or bundle.observations.output_artifacts != run.output_observations
            ):
                raise ValueError("trusted receipt and constructed bundle differ")
            self._consumed = True
            return _TrustedAdmissionCapability(
                bundle_hash=bundle.bundle_hash,
                case_id=semantic.case_id,
                workflow_revision=semantic.workflow_revision,
                nonce=self._nonce,
                _authority=_AUTHORITY,
            )


class _TrustedAdmissionCapability:
    __slots__ = (
        "_authority",
        "_bundle_hash",
        "_case_id",
        "_consumed",
        "_lock",
        "_nonce",
        "_workflow_revision",
    )

    def __init__(
        self,
        *,
        bundle_hash: str,
        case_id: str,
        workflow_revision: int,
        nonce: bytes,
        _authority: object | None = None,
    ) -> None:
        if _authority is not _AUTHORITY:
            raise TypeError("trusted admission capabilities are code-owned")
        self._authority = _authority
        self._bundle_hash = bundle_hash
        self._case_id = case_id
        self._workflow_revision = workflow_revision
        self._nonce = nonce
        self._consumed = False
        self._lock = threading.Lock()

    def consume(self, bundle: EvidenceBundle, event: AuditEvent, expected_revision: int) -> None:
        with self._lock:
            if self._authority is not _AUTHORITY or self._consumed:
                raise ValueError("trusted admission capability is invalid or already consumed")
            if (
                bundle.bundle_hash != self._bundle_hash
                or bundle.semantic.case_id != self._case_id
                or event.case_id != self._case_id
                or expected_revision != self._workflow_revision
                or bundle.semantic.workflow_revision != self._workflow_revision
            ):
                raise ValueError(
                    "trusted admission capability is bound to another bundle or revision"
                )
            self._consumed = True


def _issue_trusted_execution_receipt(
    run: EngineRun,
    *,
    case_id: str,
    workflow_revision: int,
    constitution_id: str,
    constitution_hash: str,
    amendment_chain_hash: str,
    configuration_semantic_sha256: str,
    repository_snapshot_sha256: str,
    validator_source_sha256: str,
) -> TrustedExecutionReceipt:
    if not run.validators or any(item.status != "passed" for item in run.validators):
        raise ValueError("trusted receipts require successful validator execution")
    record = _receipt_record(
        run,
        case_id=case_id,
        workflow_revision=workflow_revision,
        constitution_id=constitution_id,
        constitution_hash=constitution_hash,
        amendment_chain_hash=amendment_chain_hash,
        configuration_semantic_sha256=configuration_semantic_sha256,
        repository_snapshot_sha256=repository_snapshot_sha256,
        validator_source_sha256=validator_source_sha256,
    )
    return TrustedExecutionReceipt(record, _authority=_AUTHORITY)


__all__ = [
    "ADAPTER_CONTRACT_VERSION",
    "TrustedEngineExecution",
    "TrustedExecutionReceipt",
    "TrustedReceiptRecord",
]
