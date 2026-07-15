"""End-to-end deterministic offline tribunal scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib import resources
from pathlib import Path

from quantforge.adapters.mock import MockEvidenceAdapter, MockRoleProvider, load_scenario
from quantforge.audit import AuditLog
from quantforge.domain.constitution import create_human_approval, lock_constitution
from quantforge.domain.models import (
    ClaimScope,
    EvidenceReference,
    EvidenceRelationship,
    FindingSeverity,
    ResearchClaim,
    RoleName,
    TribunalCase,
    WorkflowState,
)
from quantforge.evidence.graph import ClaimGraph, EdgeType, GraphEdge, GraphNode, NodeType
from quantforge.evidence.ledger import EvidenceLedger, verify_source_artifact
from quantforge.roles.contracts import RoleProvider
from quantforge.verdict.policy import VerdictInputs, VerdictPolicy
from quantforge.workflow.machine import StateMachine


class DeterministicClock:
    def __init__(self) -> None:
        self._current = datetime(2026, 1, 1, tzinfo=UTC)

    def next(self) -> datetime:
        value = self._current
        self._current += timedelta(minutes=1)
        return value


@dataclass(frozen=True)
class DemoResult:
    case: TribunalCase
    evidence_ledger: EvidenceLedger
    claim_graph: ClaimGraph
    audit_log: AuditLog


def _validate_role_evidence(provider_output: object, ledger: EvidenceLedger) -> None:
    findings = getattr(provider_output, "findings", ())
    for finding in findings:
        ledger.validate_references(finding.evidence_references)
    challenges = getattr(provider_output, "challenges", ())
    for challenge in challenges:
        ledger.validate_references(challenge.evidence_references)


def _build_graph(case: TribunalCase, ledger: EvidenceLedger) -> ClaimGraph:
    graph = ClaimGraph()
    graph.add_node(
        GraphNode(
            node_id=case.claim.claim_id,
            node_type=NodeType.CLAIM,
            substantive_final_claim=True,
        )
    )
    for index, evidence in enumerate(ledger.snapshot().evidence, start=1):
        graph.add_node(
            GraphNode(
                node_id=evidence.evidence_id,
                node_type=NodeType.EVIDENCE,
                evidence_sha256=evidence.content_sha256,
                evidence_validation_status=evidence.validation_status,
            )
        )
        graph.add_edge(
            GraphEdge(
                edge_id=f"edge_{index:03d}_{case.case_id}",
                source_id=evidence.evidence_id,
                target_id=case.claim.claim_id,
                edge_type=EdgeType(evidence.relationship.value),
            )
        )
    graph.validate_final_claim_traceability()
    graph.validate_against_ledger(ledger)
    return graph


def run_demo(scenario: str) -> DemoResult:
    fixture = load_scenario(scenario)
    clock = DeterministicClock()
    claim = ResearchClaim(
        claim_id=f"claim_{fixture.name}",
        statement=fixture.claim_statement,
        submitted_by="synthetic demo operator",
        submitted_at=clock.next(),
        scope=ClaimScope(
            asset_classes=("synthetic",),
            universe=("SYNTHETIC_FIXTURE",),
            start_date="2020-01-01",
            end_date="2025-12-31",
        ),
    )
    case = TribunalCase(
        case_id=f"case_{fixture.name}",
        state=WorkflowState.CLAIM_RECEIVED,
        claim=claim,
    )
    audit = AuditLog()
    audit.append(
        timestamp=claim.submitted_at,
        case_id=case.case_id,
        workflow_state=case.state,
        actor=RoleName.SYSTEM,
        action="receive_claim",
        payload=claim,
    )
    machine = StateMachine(case, audit)

    provider: RoleProvider = MockRoleProvider(fixture, timestamp=clock.next())
    proposal = provider.propose(claim)
    machine.advance(
        WorkflowState.RESEARCHER_PROTOCOL_PROPOSED,
        actor=RoleName.RESEARCHER,
        action="propose_protocol",
        timestamp=clock.next(),
        payload=proposal,
        updates={"proposal": proposal},
    )

    provider = MockRoleProvider(fixture, timestamp=clock.next())
    methodology = provider.review_methodology(proposal)
    machine.advance(
        WorkflowState.METHODOLOGY_REVIEWED,
        actor=RoleName.METHODOLOGY_AUDITOR,
        action="review_methodology",
        timestamp=clock.next(),
        payload=methodology,
        updates={"methodology_review": methodology},
    )

    approval = create_human_approval(
        approval_id=f"approval_{fixture.name}",
        proposal=proposal,
        approver="synthetic human approver",
        approved_at=clock.next(),
    )
    machine.advance(
        WorkflowState.HUMAN_APPROVAL,
        actor=RoleName.HUMAN_APPROVER,
        action="record_approval",
        timestamp=clock.next(),
        payload=approval,
        updates={"human_approval": approval},
    )

    constitution = lock_constitution(
        constitution_id=f"constitution_{fixture.name}",
        proposal=proposal,
        approval=approval,
        locked_at=clock.next(),
    )
    machine.advance(
        WorkflowState.CONSTITUTION_LOCKED,
        actor=RoleName.SYSTEM,
        action="lock_constitution",
        timestamp=clock.next(),
        payload=constitution,
        updates={"constitution": constitution},
    )

    ledger = EvidenceLedger(
        case_id=machine.case.case_id,
        experiment_id=proposal.experiment_id,
        constitution_hash=constitution.constitution_hash,
        claim_ids={claim.claim_id},
    )
    evidence_items = MockEvidenceAdapter(fixture).load(
        claim=claim,
        case_id=machine.case.case_id,
        experiment_id=proposal.experiment_id,
        constitution_hash=constitution.constitution_hash,
        created_at=clock.next(),
    )
    artifact_root = Path(str(resources.files("quantforge.adapters")))
    for evidence in evidence_items:
        verify_source_artifact(evidence, artifact_root)
        ledger.append(evidence)
    machine.advance(
        WorkflowState.EXPERIMENT_EXECUTED,
        actor=RoleName.SYSTEM,
        action="load_mock_evidence",
        timestamp=clock.next(),
        payload=ledger.snapshot(),
        updates={"evidence_ids": tuple(item.evidence_id for item in evidence_items)},
    )

    provider = MockRoleProvider(fixture, timestamp=clock.next())
    statistical = provider.review_statistics(machine.case)
    _validate_role_evidence(statistical, ledger)
    machine.advance(
        WorkflowState.STATISTICS_REVIEWED,
        actor=RoleName.STATISTICAL_REVIEWER,
        action="review_statistics",
        timestamp=clock.next(),
        payload=statistical,
        updates={"statistical_review": statistical},
    )

    provider = MockRoleProvider(fixture, timestamp=clock.next())
    adversarial = provider.review_adversarially(machine.case)
    _validate_role_evidence(adversarial, ledger)
    machine.advance(
        WorkflowState.ADVERSARIAL_REVIEWED,
        actor=RoleName.ADVERSARIAL_REVIEWER,
        action="review_adversarially",
        timestamp=clock.next(),
        payload=adversarial,
        updates={"adversarial_review": adversarial},
    )
    machine.advance(
        WorkflowState.OPTIONAL_FOLLOW_UP,
        actor=RoleName.SYSTEM,
        action="enter_follow_up",
        timestamp=clock.next(),
        payload={"follow_up_required": False},
    )

    provider = MockRoleProvider(fixture, timestamp=clock.next())
    reproducibility = provider.review_reproducibility(machine.case)
    machine.skip_follow_up(
        actor=RoleName.REPRODUCIBILITY_REVIEWER,
        reason="No permitted follow up is required for the predefined fixture",
        timestamp=clock.next(),
        reproducibility_review=reproducibility,
    )

    decisive = tuple(
        EvidenceReference(
            evidence_id=item.evidence_id,
            numeric_fact_ids=tuple(fact.fact_id for fact in item.numeric_facts),
        )
        for item in evidence_items
    )
    ledger.validate_references(decisive)
    contradictory = tuple(
        EvidenceReference(
            evidence_id=item.evidence_id,
            numeric_fact_ids=tuple(fact.fact_id for fact in item.numeric_facts),
        )
        for item in evidence_items
        if item.relationship is EvidenceRelationship.CONTRADICTS
    )
    for reference in contradictory:
        evidence = ledger.validate_reference(reference)
        if evidence.relationship is not EvidenceRelationship.CONTRADICTS:
            raise ValueError("contradictory reference does not identify contradictory evidence")
    findings = (
        *methodology.findings,
        *statistical.findings,
        *adversarial.findings,
        *reproducibility.findings,
    )
    inputs = VerdictInputs(
        methodology_status=methodology.decision,
        primary_experiment_complete=True,
        evidence_validation_statuses=tuple(item.validation_status for item in evidence_items),
        corrected_inference=statistical.corrected_inference,
        expected_direction=proposal.primary_hypothesis.expected_direction,
        effect_direction=statistical.effect_direction,
        practical_significance=statistical.practical_significance,
        robustness_status=adversarial.robustness_status,
        cost_sensitivity=adversarial.cost_sensitivity,
        parameter_stability=adversarial.parameter_stability,
        regime_stability=adversarial.regime_stability,
        concentration_risk=adversarial.concentration_risk,
        reproducibility_status=reproducibility.status,
        unresolved_critical_findings=any(
            finding.severity is FindingSeverity.CRITICAL and not finding.resolved
            for finding in findings
        ),
        contradictory_evidence=contradictory,
        unresolved_noncritical_limitations=any(
            finding.severity is FindingSeverity.NONCRITICAL and not finding.resolved
            for finding in findings
        ),
        decisive_evidence=decisive,
    )
    eligibility = VerdictPolicy.compute(
        inputs,
        eligibility_id=f"eligibility_{fixture.name}",
        computed_at=clock.next(),
    )
    machine.advance(
        WorkflowState.VERDICT_ELIGIBILITY_COMPUTED,
        actor=RoleName.SYSTEM,
        action="compute_verdict",
        timestamp=clock.next(),
        payload={"inputs": inputs, "eligibility": eligibility},
        updates={"verdict_eligibility": eligibility},
    )

    provider = MockRoleProvider(fixture, timestamp=clock.next())
    explanation = provider.explain(machine.case, eligibility)
    ledger.validate_references(explanation.decisive_evidence)
    ledger.validate_references(explanation.contradictory_evidence)
    machine.advance(
        WorkflowState.CHAIR_EXPLANATION,
        actor=RoleName.TRIBUNAL_CHAIR,
        action="explain_verdict",
        timestamp=clock.next(),
        payload=explanation,
        updates={"chair_explanation": explanation},
    )

    graph = _build_graph(machine.case, ledger)
    audit.verify(require_complete=True)
    return DemoResult(machine.case, ledger, graph, audit)
