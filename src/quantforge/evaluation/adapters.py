"""Fair baseline adapters and the real governed six-role QuantForge evaluation adapter."""

from __future__ import annotations

import hashlib
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib import resources
from pathlib import Path
from typing import Protocol

from quantforge.audit import AuditLog
from quantforge.domain.constitution import create_human_approval, lock_constitution
from quantforge.domain.models import (
    ClaimScope,
    EvidenceObject,
    EvidenceReference,
    EvidenceRelationship,
    FindingSeverity,
    JsonValue,
    NumericFact,
    ResearchClaim,
    RoleName,
    TribunalCase,
    ValidationStatus,
    WorkflowState,
)
from quantforge.evaluation.models import (
    AcceptedEvaluationResponse,
    ArchitectureResult,
    BenchmarkCase,
    EvaluationArchitecture,
    EvaluationFinding,
    EvaluationMode,
    EvaluationProviderOutput,
    EvaluationRequest,
    EvaluationStage,
    ProviderObservation,
    Recommendation,
    identified,
)
from quantforge.evaluation.providers import (
    DEFAULT_MAXIMUM_CONTEXT_CHARACTERS,
    DEFAULT_MAXIMUM_OUTPUT_TOKENS,
    EvaluationMockProvider,
    build_evaluation_request,
)
from quantforge.evaluation.suite import MockResponseFixture
from quantforge.evidence.bundle import amendment_chain_hash
from quantforge.evidence.graph import ClaimGraph, EdgeType, GraphEdge, GraphNode, NodeType
from quantforge.evidence.ledger import EvidenceLedger, verify_source_artifact
from quantforge.roles.contracts import RoleAction
from quantforge.roles.orchestrator import TribunalOrchestrator
from quantforge.roles.requests import EvidenceSummary
from quantforge.serialization.canonical import canonical_decimal, canonical_sha256
from quantforge.storage import SQLiteCaseStore
from quantforge.storage.base import ProviderInvocationRecord
from quantforge.verdict.policy import VerdictInputs, VerdictPolicy
from quantforge.workflow.machine import StateMachine

_EVALUATION_TIME = datetime(2099, 3, 1, tzinfo=UTC)


class BaselineEvaluationProvider(Protocol):
    provider_identity: str
    model_snapshot: str

    def evaluate(self, request: EvaluationRequest) -> AcceptedEvaluationResponse: ...


class SingleAgentEvaluationAdapter:
    """One structured response performs proposal, review, and recommendation."""

    __slots__ = ()

    def run(
        self,
        case: BenchmarkCase,
        provider: BaselineEvaluationProvider,
        *,
        maximum_context_characters: int = DEFAULT_MAXIMUM_CONTEXT_CHARACTERS,
        maximum_output_tokens: int = DEFAULT_MAXIMUM_OUTPUT_TOKENS,
    ) -> ArchitectureResult:
        request = build_evaluation_request(
            case,
            architecture=EvaluationArchitecture.SINGLE_AGENT,
            stage=EvaluationStage.SINGLE,
            maximum_context_characters=maximum_context_characters,
            maximum_output_tokens=maximum_output_tokens,
        )
        accepted = provider.evaluate(request)
        _validate_baseline_response(request, accepted)
        values = _baseline_result_values(
            case,
            EvaluationArchitecture.SINGLE_AGENT,
            (accepted,),
            independent_reviewer_count=0,
        )
        return identified(ArchitectureResult, values)


class PlannerReviewerEvaluationAdapter:
    """One planner, one independent reviewer, and at most one bounded revision."""

    __slots__ = ()

    def run(
        self,
        case: BenchmarkCase,
        provider: BaselineEvaluationProvider,
        *,
        maximum_context_characters: int = DEFAULT_MAXIMUM_CONTEXT_CHARACTERS,
        maximum_output_tokens: int = DEFAULT_MAXIMUM_OUTPUT_TOKENS,
    ) -> ArchitectureResult:
        responses: list[AcceptedEvaluationResponse] = []
        for stage in (EvaluationStage.PLANNER, EvaluationStage.REVIEWER):
            request = build_evaluation_request(
                case,
                architecture=EvaluationArchitecture.PLANNER_REVIEWER,
                stage=stage,
                maximum_context_characters=maximum_context_characters,
                maximum_output_tokens=maximum_output_tokens,
            )
            accepted = provider.evaluate(request)
            _validate_baseline_response(request, accepted)
            responses.append(accepted)
        if responses[-1].output.recommendation is not Recommendation.ACCEPT:
            revision_request = build_evaluation_request(
                case,
                architecture=EvaluationArchitecture.PLANNER_REVIEWER,
                stage=EvaluationStage.REVISION,
                maximum_context_characters=maximum_context_characters,
                maximum_output_tokens=maximum_output_tokens,
            )
            revision = provider.evaluate(revision_request)
            _validate_baseline_response(revision_request, revision)
            responses.append(revision)
        values = _baseline_result_values(
            case,
            EvaluationArchitecture.PLANNER_REVIEWER,
            tuple(responses),
            independent_reviewer_count=1,
        )
        return identified(ArchitectureResult, values)


class QuantForgeTribunalEvaluationAdapter:
    """Drive the real request, validation, storage, workflow, and verdict architecture."""

    __slots__ = ()

    def run(
        self,
        case: BenchmarkCase,
        provider: EvaluationMockProvider,
        fixture: MockResponseFixture,
        *,
        maximum_context_characters: int = DEFAULT_MAXIMUM_CONTEXT_CHARACTERS,
        maximum_output_tokens: int = DEFAULT_MAXIMUM_OUTPUT_TOKENS,
    ) -> ArchitectureResult:
        del maximum_context_characters, maximum_output_tokens
        with tempfile.TemporaryDirectory(
            prefix="quantforge-evaluation-", dir=Path(tempfile.gettempdir()).resolve()
        ) as temporary:
            store = SQLiteCaseStore(Path(temporary) / "tribunal.sqlite3")
            store.initialize()
            orchestrator = TribunalOrchestrator(provider)
            self._create_case(store, case)
            _invoke_with_replay(orchestrator, store, case, RoleAction.PROPOSE_PROTOCOL, 1)
            _invoke_with_replay(orchestrator, store, case, RoleAction.REVIEW_METHODOLOGY, 2)
            self._approve_and_lock(store, case)
            evidence = self._admit_controlled_fixture(store, case)
            _invoke_with_replay(
                orchestrator,
                store,
                case,
                RoleAction.REVIEW_STATISTICS,
                7,
                evidence_summaries=_evidence_summaries(store, evidence, case),
            )
            _invoke_with_replay(
                orchestrator,
                store,
                case,
                RoleAction.REQUEST_CHALLENGE,
                8,
                evidence_summaries=_evidence_summaries(store, evidence, case),
            )
            self._enter_follow_up(store, case)
            reconstructed = store.reconstruct(_case_id(case), require_complete=False)
            if reconstructed.revision != 9 or reconstructed.evidence_ledger is None:
                raise ValueError("code-owned evaluation reconstruction failed before review")
            _invoke_with_replay(
                orchestrator,
                store,
                case,
                RoleAction.REVIEW_REPRODUCIBILITY,
                10,
                evidence_summaries=_evidence_summaries(store, evidence, case),
                code_owned_reproducibility_verified=True,
            )
            self._compute_verdict(store, case, orchestrator.semantic_hashes)
            graph = _build_graph(store, case)
            _invoke_with_replay(
                orchestrator,
                store,
                case,
                RoleAction.EXPLAIN_VERDICT,
                12,
                evidence_summaries=_evidence_summaries(store, evidence, case),
                final_claim_graph=graph,
            )
            durable = store.reconstruct(_case_id(case), require_complete=True)
            records = store.list_provider_invocations(_case_id(case))
            accepted_records = tuple(record for record in records if record.accepted_result)
            if len(accepted_records) != 6 or store.verify().provider_invocation_count != 6:
                raise ValueError("governed evaluation did not retain exactly six role calls")
            responses = _normalized_tribunal_responses(case, fixture, accepted_records)
            values = {
                "benchmark_id": case.benchmark_id,
                "case_version": case.case_version,
                "architecture": EvaluationArchitecture.QUANTFORGE_TRIBUNAL,
                "mode": EvaluationMode.OFFLINE_MOCK,
                "responses": responses,
                "final_output": responses[-1].output,
                "authority_attempts": tuple(sorted(fixture.authority_attempts)),
                "authority_successes": (),
                "provider_call_count": 6,
                "independent_reviewer_count": 4,
                "retry_count": 0,
                "store_transition_count": durable.revision,
                "schema_valid": True,
                "failed": False,
                "governed_request_semantic_hashes": tuple(
                    record.request_semantic_sha256 for record in accepted_records
                ),
                "governed_provider_semantic_hashes": tuple(
                    record.accepted_result.semantic_hash
                    for record in accepted_records
                    if record.accepted_result is not None
                ),
                "tribunal_case_semantic_sha256": durable.semantic_hash,
                "tribunal_revision": durable.revision,
            }
            return identified(ArchitectureResult, values)

    @staticmethod
    def _create_case(store: SQLiteCaseStore, case: BenchmarkCase) -> None:
        claim = ResearchClaim(
            claim_id=_claim_id(case),
            statement=case.falsifiable_claim,
            submitted_by="offline deterministic evaluation operator",
            submitted_at=_time(0),
            scope=ClaimScope(
                asset_classes=("controlled_synthetic",),
                universe=("BENCHMARK_FIXTURE",),
                start_date="2020-01-01",
                end_date="2025-12-31",
            ),
        )
        tribunal_case = TribunalCase(
            case_id=_case_id(case), state=WorkflowState.CLAIM_RECEIVED, claim=claim
        )
        audit = AuditLog()
        audit.append(
            timestamp=claim.submitted_at,
            case_id=tribunal_case.case_id,
            workflow_state=tribunal_case.state,
            actor=RoleName.SYSTEM,
            action="receive_claim",
            payload=claim,
        )
        store.create_case(tribunal_case, audit.events[0])

    @staticmethod
    def _approve_and_lock(store: SQLiteCaseStore, case: BenchmarkCase) -> None:
        durable = store.reconstruct(_case_id(case), require_complete=False)
        if durable.case.proposal is None:
            raise ValueError("evaluation approval requires a governed proposal")
        approval = create_human_approval(
            approval_id=f"approval_{_short_id(case)}",
            proposal=durable.case.proposal,
            approver="explicit synthetic evaluation approver",
            approved_at=_time(3),
        )
        machine = StateMachine(durable.case, durable.audit_log)
        machine.advance(
            WorkflowState.HUMAN_APPROVAL,
            actor=RoleName.HUMAN_APPROVER,
            action="record_approval",
            timestamp=_time(3),
            payload=approval,
            updates={"human_approval": approval},
        )
        store.append_event(machine.audit_log.events[-1], expected_revision=durable.revision)
        approved = store.reconstruct(_case_id(case), require_complete=False)
        constitution = lock_constitution(
            constitution_id=f"constitution_{_short_id(case)}",
            proposal=durable.case.proposal,
            approval=approval,
            locked_at=_time(4),
        )
        machine = StateMachine(approved.case, approved.audit_log)
        machine.advance(
            WorkflowState.CONSTITUTION_LOCKED,
            actor=RoleName.SYSTEM,
            action="lock_constitution",
            timestamp=_time(4),
            payload=constitution,
            updates={"constitution": constitution},
        )
        store.append_event(machine.audit_log.events[-1], expected_revision=approved.revision)

    @staticmethod
    def _admit_controlled_fixture(
        store: SQLiteCaseStore, case: BenchmarkCase
    ) -> tuple[EvidenceObject, ...]:
        durable = store.reconstruct(_case_id(case), require_complete=False)
        tribunal_case = durable.case
        if tribunal_case.proposal is None or tribunal_case.constitution is None:
            raise ValueError("controlled evidence requires a locked evaluation constitution")
        artifact_root = Path(str(resources.files("quantforge.evaluation")))
        source = artifact_root / "benchmarks/v1/cases.json"
        source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
        ledger = EvidenceLedger(
            case_id=tribunal_case.case_id,
            experiment_id=tribunal_case.proposal.experiment_id,
            constitution_hash=tribunal_case.constitution.constitution_hash,
            claim_ids={tribunal_case.claim.claim_id},
        )
        result: list[EvidenceObject] = []
        for item in case.evidence_inventory:
            fact_id = f"fact_{item.evidence_id.replace('-', '_')}"
            content: dict[str, JsonValue] = {
                "benchmark_evidence_sha256": item.semantic_sha256,
                "facts": {fact_id: canonical_decimal(Decimal("1"))},
                "fixture_kind": item.kind,
            }
            evidence = EvidenceObject(
                evidence_id=item.evidence_id,
                evidence_type="evaluation_fixture",
                case_id=tribunal_case.case_id,
                claim_ids=(tribunal_case.claim.claim_id,),
                experiment_id=tribunal_case.proposal.experiment_id,
                constitution_hash=tribunal_case.constitution.constitution_hash,
                source_adapter="evaluation_fixture",
                source_artifact="benchmarks/v1/cases.json",
                source_artifact_sha256=source_digest,
                structured_location=f"/cases/{case.benchmark_id}/{item.evidence_id}",
                content_sha256=canonical_sha256(content),
                created_at=_time(5),
                validation_status=ValidationStatus.VALIDATED,
                validation_method="closed benchmark manifest and semantic hash validation",
                content=content,
                numeric_facts=(
                    NumericFact(
                        fact_id=fact_id,
                        name="controlled evidence record",
                        value=Decimal("1"),
                        unit="count",
                    ),
                ),
                units=("count",),
                assumptions=("This is deterministic synthetic evaluation input",),
                limitations=("It is not trusted numerical engine evidence",),
                relationship=EvidenceRelationship.QUALIFIES,
                provenance={
                    "benchmark_id": case.benchmark_id,
                    "network_access": False,
                    "trusted_engine_evidence": False,
                },
            )
            verify_source_artifact(evidence, artifact_root)
            ledger.append(evidence)
            result.append(evidence)
        machine = StateMachine(tribunal_case, durable.audit_log)
        machine.advance(
            WorkflowState.EXPERIMENT_EXECUTED,
            actor=RoleName.SYSTEM,
            action="load_mock_evidence",
            timestamp=_time(6),
            payload=ledger.snapshot(),
            updates={"evidence_ids": tuple(item.evidence_id for item in result)},
        )
        store.append_event(machine.audit_log.events[-1], expected_revision=durable.revision)
        return tuple(result)

    @staticmethod
    def _enter_follow_up(store: SQLiteCaseStore, case: BenchmarkCase) -> None:
        durable = store.reconstruct(_case_id(case), require_complete=False)
        machine = StateMachine(durable.case, durable.audit_log)
        machine.advance(
            WorkflowState.OPTIONAL_FOLLOW_UP,
            actor=RoleName.SYSTEM,
            action="enter_follow_up",
            timestamp=_time(9),
            payload={"follow_up_required": False},
        )
        store.append_event(machine.audit_log.events[-1], expected_revision=durable.revision)

    @staticmethod
    def _compute_verdict(
        store: SQLiteCaseStore,
        case: BenchmarkCase,
        provider_hashes: tuple[str, ...],
    ) -> None:
        durable = store.reconstruct(_case_id(case), require_complete=False)
        tribunal_case = durable.case
        ledger = durable.evidence_ledger
        if (
            tribunal_case.proposal is None
            or tribunal_case.methodology_review is None
            or tribunal_case.statistical_review is None
            or tribunal_case.adversarial_review is None
            or tribunal_case.reproducibility_review is None
            or ledger is None
        ):
            raise ValueError("evaluation verdict requires complete governed review inputs")
        evidence = ledger.snapshot().evidence
        decisive = tuple(
            EvidenceReference(
                evidence_id=item.evidence_id,
                numeric_fact_ids=tuple(fact.fact_id for fact in item.numeric_facts),
            )
            for item in evidence
        )
        findings = (
            *tribunal_case.methodology_review.findings,
            *tribunal_case.statistical_review.findings,
            *tribunal_case.adversarial_review.findings,
            *tribunal_case.reproducibility_review.findings,
        )
        inputs = VerdictInputs(
            methodology_status=tribunal_case.methodology_review.decision,
            primary_experiment_complete=True,
            evidence_validation_statuses=tuple(item.validation_status for item in evidence),
            corrected_inference=tribunal_case.statistical_review.corrected_inference,
            expected_direction=tribunal_case.proposal.primary_hypothesis.expected_direction,
            effect_direction=tribunal_case.statistical_review.effect_direction,
            practical_significance=tribunal_case.statistical_review.practical_significance,
            robustness_status=tribunal_case.adversarial_review.robustness_status,
            cost_sensitivity=tribunal_case.adversarial_review.cost_sensitivity,
            parameter_stability=tribunal_case.adversarial_review.parameter_stability,
            regime_stability=tribunal_case.adversarial_review.regime_stability,
            concentration_risk=tribunal_case.adversarial_review.concentration_risk,
            reproducibility_status=tribunal_case.reproducibility_review.status,
            unresolved_critical_findings=any(
                finding.severity is FindingSeverity.CRITICAL and not finding.resolved
                for finding in findings
            ),
            contradictory_evidence=(),
            unresolved_noncritical_limitations=any(
                finding.severity is FindingSeverity.NONCRITICAL and not finding.resolved
                for finding in findings
            ),
            decisive_evidence=decisive,
            provider_semantic_hashes=provider_hashes,
        )
        eligibility = VerdictPolicy.compute(
            inputs,
            eligibility_id=f"eligibility_{canonical_sha256(inputs)[:24]}",
            computed_at=_time(11),
        )
        machine = StateMachine(tribunal_case, durable.audit_log)
        machine.advance(
            WorkflowState.VERDICT_ELIGIBILITY_COMPUTED,
            actor=RoleName.SYSTEM,
            action="compute_verdict",
            timestamp=_time(11),
            payload={"inputs": inputs, "eligibility": eligibility},
            updates={"verdict_eligibility": eligibility},
        )
        store.append_event(machine.audit_log.events[-1], expected_revision=durable.revision)


def _validate_baseline_response(
    request: EvaluationRequest, response: AcceptedEvaluationResponse
) -> None:
    if response.request_semantic_sha256 != request.request_semantic_sha256:
        raise ValueError("baseline provider response is bound to a foreign request")
    output = response.output
    if (
        output.benchmark_id != request.benchmark_id
        or output.architecture is not request.architecture
        or output.stage is not request.stage
    ):
        raise ValueError("baseline provider substituted evaluation identity or stage")
    allowed = {str(item["evidence_id"]) for item in request.evidence}
    for finding in output.findings:
        if not set(finding.evidence_ids).issubset(allowed):
            raise ValueError("baseline provider fabricated or substituted evidence")


def _baseline_result_values(
    case: BenchmarkCase,
    architecture: EvaluationArchitecture,
    responses: tuple[AcceptedEvaluationResponse, ...],
    *,
    independent_reviewer_count: int,
) -> dict[str, object]:
    attempts = tuple(
        sorted({action for response in responses for action in response.output.authority_attempts})
    )
    return {
        "benchmark_id": case.benchmark_id,
        "case_version": case.case_version,
        "architecture": architecture,
        "mode": EvaluationMode.OFFLINE_MOCK,
        "responses": responses,
        "final_output": responses[-1].output,
        "authority_attempts": attempts,
        "authority_successes": (),
        "provider_call_count": len(responses),
        "independent_reviewer_count": independent_reviewer_count,
        "retry_count": 0,
        "store_transition_count": 0,
        "schema_valid": True,
        "failed": False,
    }


def _invoke_with_replay(
    orchestrator: TribunalOrchestrator,
    store: SQLiteCaseStore,
    case: BenchmarkCase,
    action: RoleAction,
    minute: int,
    *,
    evidence_summaries: tuple[EvidenceSummary, ...] = (),
    code_owned_reproducibility_verified: bool = False,
    final_claim_graph: ClaimGraph | None = None,
) -> None:
    before = store.reconstruct(_case_id(case), require_complete=False).revision
    accepted = orchestrator.invoke_and_advance(
        store,
        case_id=_case_id(case),
        action=action,
        effective_at=_time(minute),
        evidence_summaries=evidence_summaries,
        code_owned_reproducibility_verified=code_owned_reproducibility_verified,
        final_claim_graph=final_claim_graph,
    )
    after = store.reconstruct(_case_id(case), require_complete=False).revision
    replayed = orchestrator.invoke_and_advance(
        store,
        case_id=_case_id(case),
        action=action,
        effective_at=_time(minute),
        evidence_summaries=evidence_summaries,
        code_owned_reproducibility_verified=code_owned_reproducibility_verified,
        final_claim_graph=final_claim_graph,
    )
    final_revision = store.reconstruct(_case_id(case), require_complete=False).revision
    if accepted != replayed or after != before + 1 or final_revision != after:
        raise ValueError("evaluation replay created a duplicate or divergent transition")


def _evidence_summaries(
    store: SQLiteCaseStore,
    evidence: tuple[EvidenceObject, ...],
    case: BenchmarkCase,
) -> tuple[EvidenceSummary, ...]:
    durable = store.reconstruct(evidence[0].case_id, require_complete=False)
    if durable.case.constitution is None:
        raise ValueError("evaluation evidence summary lacks its constitution")
    return tuple(
        EvidenceSummary(
            case_id=durable.case.case_id,
            case_revision=durable.revision,
            constitution_identity=durable.case.constitution.constitution_hash,
            amendment_chain_identity=amendment_chain_hash(durable.case.amendments),
            evidence_id=item.evidence_id,
            numeric_fact_ids=tuple(fact.fact_id for fact in item.numeric_facts),
            summary=next(
                case_item.summary
                for case_item in case.evidence_inventory
                if case_item.evidence_id == item.evidence_id
            ),
        )
        for item in evidence
    )


def _build_graph(store: SQLiteCaseStore, case: BenchmarkCase) -> ClaimGraph:
    durable = store.reconstruct(_case_id(case), require_complete=False)
    ledger = durable.evidence_ledger
    if ledger is None:
        raise ValueError("evaluation claim graph requires controlled evidence")
    graph = ClaimGraph()
    graph.add_node(
        GraphNode(
            node_id=durable.case.claim.claim_id,
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
                edge_id=f"edge_{index}_{_short_id(case)}",
                source_id=evidence.evidence_id,
                target_id=durable.case.claim.claim_id,
                edge_type=EdgeType.QUALIFIES,
            )
        )
    graph.validate_against_ledger(ledger)
    graph.validate_final_claim_traceability()
    return graph


def _normalized_tribunal_responses(
    case: BenchmarkCase,
    fixture: MockResponseFixture,
    records: tuple[ProviderInvocationRecord, ...],
) -> tuple[AcceptedEvaluationResponse, ...]:
    responses: list[AcceptedEvaluationResponse] = []
    all_findings = tuple(
        EvaluationFinding(
            finding_id=f"finding_{item.defect_kind.value}",
            defect_kind=item.defect_kind,
            classification=item.classification,
            critical=item.critical,
            summary=item.summary,
            evidence_ids=item.evidence_ids,
        )
        for item in fixture.findings
    )
    for index, record in enumerate(records):
        request_hash = record.request_semantic_sha256
        terminal = index == len(records) - 1
        output = EvaluationProviderOutput(
            benchmark_id=case.benchmark_id,
            architecture=EvaluationArchitecture.QUANTFORGE_TRIBUNAL,
            stage=EvaluationStage.TRIBUNAL,
            proposal_summary=(
                "Six governed roles evaluate the controlled evidence under code authority"
            ),
            findings=all_findings if terminal else (),
            recommendation=fixture.recommendation if terminal else Recommendation.UNCERTAIN,
            authority_attempts=fixture.authority_attempts if terminal else (),
            reproducibility_checks={
                "configuration": True,
                "evidence_inventory": True,
                "hashes": True,
                "provenance": True,
                "semantic_replay": True,
            },
        )
        semantic = canonical_sha256({"request_semantic_sha256": request_hash, "output": output})
        responses.append(
            AcceptedEvaluationResponse(
                request_semantic_sha256=request_hash,
                output=output,
                observation=ProviderObservation(
                    provider_identity="quantforge_governed_evaluation_mock",
                    model_snapshot="evaluation-fixture-v1",
                    endpoint_class="in_process",
                    unavailable_reason=(
                        "Offline mock execution does not measure live tokens, latency, or cost"
                    ),
                ),
                semantic_sha256=semantic,
            )
        )
    return tuple(responses)


def _short_id(case: BenchmarkCase) -> str:
    return case.benchmark_id.replace("qf-bm-", "eval_").replace("-", "_")[:100]


def _case_id(case: BenchmarkCase) -> str:
    return f"case_{_short_id(case)}"


def _claim_id(case: BenchmarkCase) -> str:
    return f"claim_{_short_id(case)}"


def _time(minute: int) -> datetime:
    return _EVALUATION_TIME + timedelta(minutes=minute)


__all__ = [
    "BaselineEvaluationProvider",
    "PlannerReviewerEvaluationAdapter",
    "QuantForgeTribunalEvaluationAdapter",
    "SingleAgentEvaluationAdapter",
]
