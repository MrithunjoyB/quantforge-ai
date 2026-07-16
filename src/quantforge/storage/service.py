"""Backend-neutral persistence orchestration for already-governed case histories."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from quantforge.audit import AuditLog
from quantforge.domain.models import EvidenceObject, RoleName, WorkflowState
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
    """Verify and atomically admit one engine bundle plus its workflow event."""

    durable = store.reconstruct(context.case_id, require_complete=False)
    case = durable.case
    if (
        case.state is not WorkflowState.CONSTITUTION_LOCKED
        or case.constitution is None
        or case.proposal is None
    ):
        raise ValueError("engine evidence requires a locked, not-yet-executed constitution")
    if (
        context.case_id != case.case_id
        or context.workflow_revision != durable.revision
        or context.constitution_id != case.constitution.constitution_id
        or context.constitution_hash != case.constitution.constitution_hash
        or context.amendment_chain_hash != amendment_chain_hash(case.amendments)
        or context.finalized
        or context.previous_bundle_hash != GENESIS_BUNDLE_HASH
    ):
        raise ValueError("evidence admission context does not match durable governed state")
    verify_evidence_bundle(bundle, context, artifact_root, signer=signer)
    evidence = evidence_from_bundle(
        bundle,
        evidence_id=evidence_id,
        claim_id=case.claim.claim_id,
        experiment_id=case.proposal.experiment_id,
    )
    verify_source_artifact(evidence, artifact_root, max_bytes=16 * 1024 * 1024)
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
    store.admit_evidence_bundle(bundle, event, expected_revision=durable.revision)
    return EvidenceAdmissionResult(
        bundle=bundle,
        evidence=evidence,
        durable_case=store.reconstruct(case.case_id, require_complete=False),
    )


__all__ = ["EvidenceAdmissionResult", "admit_engine_evidence", "persist_audited_case"]
