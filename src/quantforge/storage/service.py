"""Backend-neutral persistence orchestration for already-governed case histories."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from quantforge.audit import AuditLog
from quantforge.domain.models import EvidenceObject, RoleName, WorkflowState
from quantforge.engine.base import EngineAdapter
from quantforge.evidence.bundle import (
    GENESIS_BUNDLE_HASH,
    BundleSigner,
    EvidenceAdmissionContext,
    EvidenceBundle,
    amendment_chain_hash,
    evidence_from_bundle,
    verify_evidence_bundle,
)
from quantforge.evidence.graph import ClaimGraph
from quantforge.evidence.ledger import EvidenceLedger, verify_source_artifact
from quantforge.serialization.canonical import canonical_sha256
from quantforge.storage.base import CaseStore, DurableCase
from quantforge.workflow.machine import StateMachine


@dataclass(frozen=True)
class EvidenceAdmissionResult:
    bundle: EvidenceBundle
    evidence: EvidenceObject
    durable_case: DurableCase


def persist_audited_case(
    store: CaseStore,
    audit_log: AuditLog,
    *,
    claim_graph: ClaimGraph | None = None,
) -> DurableCase:
    """Persist one verified history using atomic creation and revision-checked appends."""

    audit_log.verify(require_complete=False)
    cases = audit_log.replay_cases(require_complete=False)
    events = audit_log.events
    if not cases or len(cases) != len(events):
        raise ValueError("audited case persistence requires a nonempty replayable history")
    if cases[-1].state is WorkflowState.CHAIR_EXPLANATION and claim_graph is None:
        raise ValueError("finalized audited cases require a revision-anchored claim graph")
    store.create_case(cases[0], events[0])
    for expected_revision, event in enumerate(events[1:], start=1):
        store.append_event(event, expected_revision=expected_revision)
    if claim_graph is not None:
        store.save_claim_graph(cases[-1].case_id, claim_graph, expected_revision=len(events))
    return store.reconstruct(
        cases[-1].case_id,
        require_complete=cases[-1].chair_explanation is not None,
    )


def admit_engine_evidence(
    store: CaseStore,
    bundle: EvidenceBundle,
    context: EvidenceAdmissionContext,
    artifact_root: Path,
    *,
    evidence_id: str,
    signer: BundleSigner | None = None,
) -> EvidenceAdmissionResult:
    """Reject delayed/serialized admission: integrity verification is a separate operation."""

    del store, bundle, context, artifact_root, evidence_id, signer
    raise ValueError("standalone engine evidence admission is unsupported; use execute-and-admit")


def execute_and_admit_engine_evidence(
    store: CaseStore,
    adapter: EngineAdapter,
    *,
    case_id: str,
    evidence_id: str,
    signer: BundleSigner | None = None,
) -> EvidenceAdmissionResult:
    """Execute, independently validate, construct, verify, and atomically admit in-process."""

    durable = store.reconstruct(case_id, require_complete=False)
    case = durable.case
    if (
        case.state is not WorkflowState.CONSTITUTION_LOCKED
        or case.constitution is None
        or case.proposal is None
    ):
        raise ValueError("engine evidence requires a locked, not-yet-executed constitution")
    if durable.evidence_ledger is not None or store.list_evidence_bundles(case_id):
        raise ValueError("primary engine evidence has already been admitted")
    chain_hash = amendment_chain_hash(case.amendments)
    execution = adapter.execute_trusted_fixture(
        case_id=case.case_id,
        workflow_revision=durable.revision,
        constitution_id=case.constitution.constitution_id,
        constitution_hash=case.constitution.constitution_hash,
        amendment_chain_hash=chain_hash,
    )
    run = execution.run
    admitted_at = datetime.now(UTC)
    bundle_identity = {
        "case_id": case.case_id,
        "revision": durable.revision,
        "run": execution.receipt.record.run_fingerprint,
    }
    bundle_id = f"bundle_{canonical_sha256(bundle_identity)[:32]}"
    bundle = run.evidence_bundle(
        bundle_id=bundle_id,
        case_id=case.case_id,
        workflow_revision=durable.revision,
        constitution_id=case.constitution.constitution_id,
        constitution_hash=case.constitution.constitution_hash,
        amendment_chain_hash=chain_hash,
        previous_bundle_hash=GENESIS_BUNDLE_HASH,
        admitted_at=admitted_at,
        signer=signer,
    )
    context = EvidenceAdmissionContext(
        case_id=case.case_id,
        workflow_revision=durable.revision,
        constitution_id=case.constitution.constitution_id,
        constitution_hash=case.constitution.constitution_hash,
        amendment_chain_hash=chain_hash,
        engine=run.engine,
        configuration_sha256=run.configuration_sha256,
        input_artifacts=run.input_semantics,
        input_artifact_observations=run.input_observations,
        previous_bundle_hash=GENESIS_BUNDLE_HASH,
        now=admitted_at,
    )
    verify_evidence_bundle(bundle, context, run.output_root, signer=signer)
    evidence = evidence_from_bundle(
        bundle,
        evidence_id=evidence_id,
        claim_id=case.claim.claim_id,
        experiment_id=case.proposal.experiment_id,
    )
    verify_source_artifact(evidence, run.output_root, max_bytes=16 * 1024 * 1024)
    ledger = EvidenceLedger(
        case_id=case.case_id,
        experiment_id=case.proposal.experiment_id,
        constitution_hash=case.constitution.constitution_hash,
        claim_ids={case.claim.claim_id},
    )
    ledger.append(evidence)
    machine = StateMachine(case, durable.audit_log)
    machine.advance(
        WorkflowState.EXPERIMENT_EXECUTED,
        actor=RoleName.SYSTEM,
        action="admit_engine_evidence",
        timestamp=bundle.observations.admitted_at,
        payload=ledger.snapshot(),
        updates={"evidence_ids": (evidence.evidence_id,)},
    )
    event = machine.audit_log.events[-1]
    receipt_record = execution.receipt.record
    capability = execution.receipt._consume(
        run,
        bundle,
        configuration_semantic_sha256=receipt_record.configuration_semantic_sha256,
        repository_snapshot_sha256=receipt_record.repository_snapshot_sha256,
        validator_source_sha256=receipt_record.validator_source_sha256,
    )
    store.admit_evidence_bundle(
        bundle,
        event,
        expected_revision=durable.revision,
        capability=capability,
    )
    return EvidenceAdmissionResult(
        bundle=bundle,
        evidence=evidence,
        durable_case=store.reconstruct(case.case_id, require_complete=False),
    )


__all__ = [
    "EvidenceAdmissionResult",
    "admit_engine_evidence",
    "execute_and_admit_engine_evidence",
    "persist_audited_case",
]
