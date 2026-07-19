"""Backend-neutral persistence orchestration for already-governed case histories."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from quantforge.audit import AuditLog
from quantforge.domain.models import EvidenceObject, RoleName, WorkflowState
from quantforge.engine.base import EngineAdapter
from quantforge.engine.trust import TrustedReceiptRecord
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
    evidence_items: tuple[EvidenceObject, ...]
    trusted_receipt: TrustedReceiptRecord
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
    admitted_at: datetime | None = None,
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
    effective_admitted_at = admitted_at or datetime.now(UTC)
    if effective_admitted_at < run.execution_completed_at:
        raise ValueError("evidence admission time precedes trusted execution completion")
    bundle_identity = {
        "case_id": case.case_id,
        "configuration_sha256": run.configuration_sha256,
        "constitution_hash": case.constitution.constitution_hash,
        "engine": run.engine,
        "input_artifacts": run.input_semantics,
        "invocation": run.invocation,
        "numeric_facts": run.numeric_facts,
        "output_artifacts": run.output_semantics,
        "previous_bundle_hash": GENESIS_BUNDLE_HASH,
        "revision": durable.revision,
        "validator_results": run.validators,
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
        admitted_at=effective_admitted_at,
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
        now=effective_admitted_at,
    )
    verify_evidence_bundle(bundle, context, run.output_root, signer=signer)
    fact_ids_by_artifact: dict[str, list[str]] = {}
    for fact in bundle.semantic.numeric_facts:
        fact_ids_by_artifact.setdefault(fact.artifact_path, []).append(fact.fact_id)
    evidence_items: list[EvidenceObject] = []
    for artifact_path, fact_ids in sorted(fact_ids_by_artifact.items()):
        derived_id = (
            evidence_id
            if len(fact_ids_by_artifact) == 1
            else f"{evidence_id[:96]}_{canonical_sha256(artifact_path)[:16]}"
        )
        item = evidence_from_bundle(
            bundle,
            evidence_id=derived_id,
            claim_id=case.claim.claim_id,
            experiment_id=case.proposal.experiment_id,
            numeric_fact_ids=tuple(sorted(fact_ids)),
        )
        verify_source_artifact(item, run.output_root, max_bytes=16 * 1024 * 1024)
        evidence_items.append(item)
    if not evidence_items:
        raise ValueError("trusted engine bundle contains no admissible evidence groups")
    evidence = next(
        (
            item
            for item in evidence_items
            if item.source_artifact.endswith("portfolio_performance_summary.csv")
        ),
        evidence_items[0],
    )
    ledger = EvidenceLedger(
        case_id=case.case_id,
        experiment_id=case.proposal.experiment_id,
        constitution_hash=case.constitution.constitution_hash,
        claim_ids={case.claim.claim_id},
    )
    for item in evidence_items:
        ledger.append(item)
    machine = StateMachine(case, durable.audit_log)
    machine.advance(
        WorkflowState.EXPERIMENT_EXECUTED,
        actor=RoleName.SYSTEM,
        action="admit_engine_evidence",
        timestamp=bundle.observations.admitted_at,
        payload=ledger.snapshot(),
        updates={"evidence_ids": tuple(item.evidence_id for item in evidence_items)},
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
        evidence_items=tuple(evidence_items),
        trusted_receipt=receipt_record,
        durable_case=store.reconstruct(case.case_id, require_complete=False),
    )


__all__ = [
    "EvidenceAdmissionResult",
    "admit_engine_evidence",
    "execute_and_admit_engine_evidence",
    "persist_audited_case",
]
