"""Deterministic typed mock roles and mock evidence fixtures for offline Phase 1."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from importlib import resources
from typing import Literal, cast

from pydantic import Field, model_validator

from quantforge.domain.models import (
    AdversarialChallenge,
    AdversarialReview,
    BenchmarkDefinition,
    ChairExplanation,
    ChallengeStatus,
    ChallengeType,
    CorrectedInference,
    DataRequirement,
    EvidenceObject,
    EvidenceReference,
    EvidenceRelationship,
    ExecutionAssumption,
    ExperimentProposal,
    FailureCriterion,
    FindingSeverity,
    GateStatus,
    JsonValue,
    MethodologyReview,
    MetricDefinition,
    Money,
    NarrativeText,
    NullHypothesis,
    NumericFact,
    PrimaryHypothesis,
    Rate,
    ReproducibilityReview,
    ReproducibilityStatus,
    ResearchClaim,
    ReviewDecision,
    ReviewerFinding,
    RoleName,
    Sensitivity,
    Stability,
    StatisticalReview,
    StrictModel,
    TribunalCase,
    Unit,
    ValidationStatus,
    VerdictEligibility,
)
from quantforge.roles.chair import create_chair_explanation
from quantforge.roles.contracts import (
    ProviderAttemptObservation,
    ProviderCallContext,
    ProviderObservationalProvenance,
    ProviderResult,
    ProviderResultAny,
    ProviderTransportOutcome,
    RoleAction,
    RoleAuthority,
    create_provider_result,
)
from quantforge.roles.requests import ContextKind, EvidenceSummary, GovernedRoleRequest
from quantforge.serialization.canonical import canonical_decimal, canonical_sha256


class FixtureFact(StrictModel):
    fact_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,127}$")
    name: str
    value: Decimal
    unit: Unit


class FixtureEvidence(StrictModel):
    evidence_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,127}$")
    evidence_type: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,127}$")
    relationship: EvidenceRelationship
    validation_status: ValidationStatus
    facts: tuple[FixtureFact, ...] = Field(min_length=1)
    limitation: NarrativeText


class ScenarioFixture(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    name: Literal["provisional", "fragile", "inconclusive", "governed_tribunal"]
    claim_statement: NarrativeText
    methodology_decision: ReviewDecision
    corrected_inference: CorrectedInference
    effect_direction: Literal["positive", "negative", "null", "mixed"]
    practical_significance: bool
    robustness_status: GateStatus
    cost_sensitivity: Sensitivity
    parameter_stability: Stability
    regime_stability: Stability
    concentration_risk: Sensitivity
    reproducibility_status: ReproducibilityStatus
    contradictory_evidence: bool
    unresolved_noncritical_limitations: bool
    evidence: tuple[FixtureEvidence, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def policy_flags_match_evidence(self) -> ScenarioFixture:
        has_contradiction = any(
            item.relationship is EvidenceRelationship.CONTRADICTS for item in self.evidence
        )
        if self.contradictory_evidence != has_contradiction:
            raise ValueError("fixture contradiction flag does not match structured evidence")
        return self


def load_scenario(name: str) -> ScenarioFixture:
    if name not in {"provisional", "fragile", "inconclusive", "governed_tribunal"}:
        raise ValueError("unknown synthetic demo scenario")
    fixture = resources.files("quantforge.adapters.fixtures").joinpath(f"{name}.json")
    return ScenarioFixture.model_validate_json(fixture.read_text(encoding="utf-8"))


class MockEvidenceAdapter:
    """Loads only package-owned fixtures and never executes commands or accesses external paths."""

    adapter_id = "mock_evidence"

    def __init__(self, fixture: ScenarioFixture) -> None:
        self._fixture = fixture

    def load(
        self,
        *,
        claim: ResearchClaim,
        case_id: str,
        experiment_id: str,
        constitution_hash: str,
        created_at: datetime,
    ) -> tuple[EvidenceObject, ...]:
        result: list[EvidenceObject] = []
        source = resources.files("quantforge.adapters").joinpath(
            f"fixtures/{self._fixture.name}.json"
        )
        source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
        for item in self._fixture.evidence:
            content: dict[str, JsonValue] = {
                "classification": "synthetic_validation_only",
                "facts": {fact.fact_id: canonical_decimal(fact.value) for fact in item.facts},
                "scenario": self._fixture.name,
            }
            result.append(
                EvidenceObject(
                    evidence_id=item.evidence_id,
                    evidence_type=item.evidence_type,
                    case_id=case_id,
                    claim_ids=(claim.claim_id,),
                    experiment_id=experiment_id,
                    constitution_hash=constitution_hash,
                    source_adapter=self.adapter_id,
                    source_artifact=f"fixtures/{self._fixture.name}.json",
                    source_artifact_sha256=source_digest,
                    structured_location="/evidence",
                    content_sha256=canonical_sha256(content),
                    created_at=created_at,
                    validation_status=item.validation_status,
                    validation_method="canonical fixture schema and content hash",
                    content=content,
                    numeric_facts=tuple(NumericFact(**fact.model_dump()) for fact in item.facts),
                    units=tuple(sorted({fact.unit for fact in item.facts})),
                    assumptions=("All observations are synthetic validation data",),
                    limitations=(item.limitation,),
                    relationship=item.relationship,
                    provenance={
                        "generator": "quantforge_typed_mock",
                        "network_access": False,
                        "real_profitability_claim": False,
                    },
                )
            )
        return tuple(result)


class MockRoleProvider:
    """Predefined typed outputs exercising the same boundaries required of future LLM adapters."""

    provider_identity = "quantforge_mock_provider"
    model_snapshot = "typed-fixture-v1"
    endpoint_class = "in_process"
    sdk_version = "quantforge-in-process"

    def __init__(
        self,
        fixture: ScenarioFixture,
        *,
        timestamp: datetime | None = None,
        timestamp_factory: Callable[[], datetime] | None = None,
    ) -> None:
        if (timestamp is None) == (timestamp_factory is None):
            raise ValueError("mock provider requires exactly one deterministic clock source")
        self._fixture = fixture
        self._timestamp = timestamp
        self._timestamp_factory = timestamp_factory

    def propose(self, claim: ResearchClaim) -> ProviderResult[ExperimentProposal]:
        RoleAuthority.require(RoleName.RESEARCHER, RoleAction.PROPOSE_PROTOCOL)
        suffix = self._fixture.name
        timestamp = self._now()
        output = ExperimentProposal(
            experiment_id=f"experiment_{suffix}",
            claim_id=claim.claim_id,
            primary_hypothesis=PrimaryHypothesis(
                hypothesis_id=f"primary_{suffix}",
                statement=(
                    "The synthetic signal has positive benchmark relative evidence after costs"
                ),
                expected_direction="positive",
            ),
            null_hypothesis=NullHypothesis(
                hypothesis_id=f"null_{suffix}",
                statement=(
                    "The synthetic signal has no positive benchmark relative evidence after costs"
                ),
            ),
            metrics=(
                MetricDefinition(
                    metric_id=f"metric_{suffix}",
                    name="benchmark relative effect",
                    unit="basis_points",
                    calculation="Compare frozen out of sample signal and benchmark outcomes",
                    primary=True,
                ),
            ),
            data_requirements=(
                DataRequirement(
                    requirement_id=f"data_{suffix}",
                    description="Versioned synthetic observations with complete lineage",
                ),
            ),
            execution_assumptions=(
                ExecutionAssumption(
                    assumption_id=f"execution_{suffix}",
                    description="Causal next observation execution with explicit costs",
                    commission=Rate(value=Decimal("5"), unit="basis_points"),
                    slippage=Rate(value=Decimal("5"), unit="basis_points"),
                    starting_capital=Money(amount=Decimal("100000"), currency="USD"),
                ),
            ),
            benchmarks=(
                BenchmarkDefinition(
                    benchmark_id=f"benchmark_{suffix}",
                    name="synthetic parity benchmark",
                    parity_rule="Apply the same period and execution cost assumptions",
                ),
            ),
            periods=("synthetic training period", "synthetic frozen evaluation period"),
            exclusions=("real market interpretation", "financial execution"),
            failure_criteria=(
                FailureCriterion(
                    criterion_id=f"failure_{suffix}",
                    description=(
                        "Reject positive interpretation when a decisive governance gate fails"
                    ),
                ),
            ),
            proposed_at=timestamp,
        )
        return self._result(
            RoleAction.PROPOSE_PROTOCOL,
            output,
            timestamp,
            ProviderResult[ExperimentProposal],
        )

    def review_methodology(self, proposal: ExperimentProposal) -> ProviderResult[MethodologyReview]:
        RoleAuthority.require(RoleName.METHODOLOGY_AUDITOR, RoleAction.REVIEW_METHODOLOGY)
        timestamp = self._now()
        output = MethodologyReview(
            review_id=f"methodology_{self._fixture.name}",
            experiment_id=proposal.experiment_id,
            decision=self._fixture.methodology_decision,
            causality_checked=True,
            leakage_checked=True,
            benchmark_parity_checked=True,
            execution_assumptions_checked=True,
            multiple_testing_checked=True,
            evaluable=True,
            findings=(),
            reviewed_at=timestamp,
        )
        return self._result(
            RoleAction.REVIEW_METHODOLOGY,
            output,
            timestamp,
            ProviderResult[MethodologyReview],
        )

    def review_statistics(self, case: TribunalCase) -> ProviderResult[StatisticalReview]:
        RoleAuthority.require(RoleName.STATISTICAL_REVIEWER, RoleAction.REVIEW_STATISTICS)
        timestamp = self._now()
        references = tuple(
            EvidenceReference(
                evidence_id=item.evidence_id, numeric_fact_ids=(item.facts[0].fact_id,)
            )
            for item in self._fixture.evidence
        )
        output = StatisticalReview(
            review_id=f"statistics_{self._fixture.name}",
            effect_direction=self._fixture.effect_direction,
            corrected_inference=self._fixture.corrected_inference,
            practical_significance=self._fixture.practical_significance,
            findings=(
                ReviewerFinding(
                    finding_id=f"stat_finding_{self._fixture.name}",
                    severity=FindingSeverity.NONCRITICAL,
                    summary=(
                        "The structured inference result is bound to validated synthetic evidence"
                    ),
                    evidence_references=references,
                    resolved=not self._fixture.unresolved_noncritical_limitations,
                ),
            ),
            sample_limitations=("The synthetic sample cannot establish real market performance",),
            reviewed_at=timestamp,
        )
        return self._result(
            RoleAction.REVIEW_STATISTICS,
            output,
            timestamp,
            ProviderResult[StatisticalReview],
        )

    def review_adversarially(self, case: TribunalCase) -> ProviderResult[AdversarialReview]:
        RoleAuthority.require(RoleName.ADVERSARIAL_REVIEWER, RoleAction.REQUEST_CHALLENGE)
        timestamp = self._now()
        reference = EvidenceReference(
            evidence_id=self._fixture.evidence[-1].evidence_id,
            numeric_fact_ids=(self._fixture.evidence[-1].facts[0].fact_id,),
        )
        status = (
            ChallengeStatus.FAILED
            if self._fixture.robustness_status is GateStatus.FAIL
            else ChallengeStatus.PASSED
        )
        output = AdversarialReview(
            review_id=f"adversarial_{self._fixture.name}",
            challenges=(
                AdversarialChallenge(
                    challenge_id=f"cost_challenge_{self._fixture.name}",
                    challenge_type=ChallengeType.COST,
                    description="Stress explicit costs and robustness assumptions",
                    status=status,
                    evidence_references=(reference,),
                ),
            ),
            robustness_status=self._fixture.robustness_status,
            cost_sensitivity=self._fixture.cost_sensitivity,
            parameter_stability=self._fixture.parameter_stability,
            regime_stability=self._fixture.regime_stability,
            concentration_risk=self._fixture.concentration_risk,
            findings=(),
            reviewed_at=timestamp,
        )
        return self._result(
            RoleAction.REQUEST_CHALLENGE,
            output,
            timestamp,
            ProviderResult[AdversarialReview],
        )

    def review_reproducibility(self, case: TribunalCase) -> ProviderResult[ReproducibilityReview]:
        RoleAuthority.require(RoleName.REPRODUCIBILITY_REVIEWER, RoleAction.REVIEW_REPRODUCIBILITY)
        timestamp = self._now()
        verified = self._fixture.reproducibility_status is ReproducibilityStatus.VERIFIED
        output = ReproducibilityReview(
            review_id=f"reproducibility_{self._fixture.name}",
            status=self._fixture.reproducibility_status,
            configuration_verified=verified,
            manifests_verified=verified,
            hashes_verified=verified,
            software_identity_verified=verified,
            data_lineage_verified=verified,
            evidence_complete=verified,
            reconstruction_status="verified" if verified else "failed",
            findings=(),
            reviewed_at=timestamp,
        )
        return self._result(
            RoleAction.REVIEW_REPRODUCIBILITY,
            output,
            timestamp,
            ProviderResult[ReproducibilityReview],
        )

    def explain(
        self, case: TribunalCase, eligibility: VerdictEligibility
    ) -> ProviderResult[ChairExplanation]:
        RoleAuthority.require(RoleName.TRIBUNAL_CHAIR, RoleAction.EXPLAIN_VERDICT)
        timestamp = self._now()
        output = create_chair_explanation(
            explanation_id=f"chair_{self._fixture.name}",
            eligibility=eligibility,
            requested_verdict=eligibility.verdict,
            summary=(
                "The deterministic policy result follows the governed evidence and review gates"
            ),
            limitations=(
                "Synthetic evidence cannot support financial advice or real profitability claims",
            ),
            verdict_change_conditions=(
                "The verdict may change only when validated evidence changes a policy gate",
            ),
            created_at=timestamp,
        )
        return self._result(
            RoleAction.EXPLAIN_VERDICT,
            output,
            timestamp,
            ProviderResult[ChairExplanation],
        )

    def invoke(self, request: GovernedRoleRequest) -> ProviderResultAny:
        """Exercise the governed request path without network access or extra authority."""

        RoleAuthority.require(request.role, request.action)
        context = ProviderCallContext(
            role=request.role,
            action=request.action,
            case_id=request.case_id,
            case_revision=request.case_revision,
            constitution_identity=request.constitution_identity,
            amendment_chain_identity=request.amendment_chain_identity,
            evidence_references=request.evidence_references,
            context_item_identities=tuple(item.identity for item in request.context),
            role_context_sha256=request.context_identity,
            canonical_request_sha256=request.request_semantic_sha256,
        )
        if request.action is RoleAction.PROPOSE_PROTOCOL:
            claim = self._context_model(request, ContextKind.USER_CLAIM, ResearchClaim)
            proposal_output = self.propose(claim).output.model_copy(
                update={
                    "experiment_id": request.expected_output_id,
                    "proposed_at": request.effective_at,
                }
            )
            return self._result(
                request.action,
                proposal_output,
                request.effective_at,
                ProviderResult[ExperimentProposal],
                call_context=context,
            )
        elif request.action is RoleAction.REVIEW_METHODOLOGY:
            proposal = self._context_model(request, ContextKind.PROPOSAL, ExperimentProposal)
            methodology_output = self.review_methodology(proposal).output.model_copy(
                update={
                    "review_id": request.expected_output_id,
                    "reviewed_at": request.effective_at,
                }
            )
            return self._result(
                request.action,
                methodology_output,
                request.effective_at,
                ProviderResult[MethodologyReview],
                call_context=context,
            )
        elif request.action is RoleAction.REVIEW_STATISTICS:
            references = self._request_evidence_references(request)
            initial_statistics = self.review_statistics(cast(TribunalCase, object())).output
            findings = tuple(
                finding.model_copy(update={"evidence_references": references})
                for finding in initial_statistics.findings
            )
            statistical_output = initial_statistics.model_copy(
                update={
                    "review_id": request.expected_output_id,
                    "reviewed_at": request.effective_at,
                    "findings": findings,
                }
            )
            return self._result(
                request.action,
                statistical_output,
                request.effective_at,
                ProviderResult[StatisticalReview],
                call_context=context,
            )
        elif request.action is RoleAction.REQUEST_CHALLENGE:
            references = self._request_evidence_references(request)
            initial_adversarial = self.review_adversarially(cast(TribunalCase, object())).output
            challenges = tuple(
                challenge.model_copy(update={"evidence_references": references})
                for challenge in initial_adversarial.challenges
            )
            findings = tuple(
                finding.model_copy(update={"evidence_references": references})
                for finding in initial_adversarial.findings
            )
            adversarial_output = initial_adversarial.model_copy(
                update={
                    "review_id": request.expected_output_id,
                    "reviewed_at": request.effective_at,
                    "challenges": challenges,
                    "findings": findings,
                }
            )
            return self._result(
                request.action,
                adversarial_output,
                request.effective_at,
                ProviderResult[AdversarialReview],
                call_context=context,
            )
        elif request.action is RoleAction.REVIEW_REPRODUCIBILITY:
            reproducibility_output = self.review_reproducibility(
                cast(TribunalCase, object())
            ).output
            if not request.code_owned_reproducibility_verified:
                reproducibility_output = reproducibility_output.model_copy(
                    update={
                        "status": ReproducibilityStatus.PARTIAL,
                        "configuration_verified": False,
                        "manifests_verified": False,
                        "hashes_verified": False,
                        "software_identity_verified": False,
                        "data_lineage_verified": False,
                        "evidence_complete": False,
                        "reconstruction_status": "Code owned verification was not supplied",
                    }
                )
            reproducibility_output = reproducibility_output.model_copy(
                update={
                    "review_id": request.expected_output_id,
                    "reviewed_at": request.effective_at,
                }
            )
            return self._result(
                request.action,
                reproducibility_output,
                request.effective_at,
                ProviderResult[ReproducibilityReview],
                call_context=context,
            )
        elif request.action is RoleAction.EXPLAIN_VERDICT:
            eligibility = self._context_model(
                request,
                ContextKind.VERDICT_ELIGIBILITY,
                VerdictEligibility,
            )
            chair_output = self.explain(
                cast(TribunalCase, object()), eligibility
            ).output.model_copy(
                update={
                    "explanation_id": request.expected_output_id,
                    "created_at": request.effective_at,
                }
            )
            return self._result(
                request.action,
                chair_output,
                request.effective_at,
                ProviderResult[ChairExplanation],
                call_context=context,
            )
        else:  # pragma: no cover - RoleAuthority rejects every non-governed action.
            raise PermissionError("mock provider action is not governed")

    @staticmethod
    def _context_model[ModelT: StrictModel](
        request: GovernedRoleRequest,
        kind: ContextKind,
        model_type: type[ModelT],
    ) -> ModelT:
        matches = [item for item in request.context if item.kind is kind]
        if len(matches) != 1:
            raise ValueError(f"governed mock request requires exactly one {kind.value} item")
        return model_type.model_validate_json(matches[0].content, strict=True)

    @staticmethod
    def _request_evidence_references(
        request: GovernedRoleRequest,
    ) -> tuple[EvidenceReference, ...]:
        summaries = (
            EvidenceSummary.model_validate_json(item.content, strict=True)
            for item in request.context
            if item.kind is ContextKind.EVIDENCE_SUMMARY
        )
        references = tuple(
            EvidenceReference(
                evidence_id=summary.evidence_id,
                numeric_fact_ids=summary.numeric_fact_ids,
            )
            for summary in summaries
        )
        if not references:
            raise ValueError("governed mock review requires supplied evidence summaries")
        return references

    def _now(self) -> datetime:
        if self._timestamp_factory is not None:
            return self._timestamp_factory()
        if self._timestamp is None:
            raise RuntimeError("mock provider has no deterministic timestamp")
        return self._timestamp

    def _result[ResultT: StrictModel](
        self,
        action: RoleAction,
        output: ResultT,
        timestamp: datetime,
        result_type: type[ProviderResult[ResultT]],
        *,
        call_context: ProviderCallContext | None = None,
    ) -> ProviderResult[ResultT]:
        suffix = f"{action.value}_{self._fixture.name}"
        attempts = (
            ()
            if call_context is None
            else (
                ProviderAttemptObservation(
                    attempt_index=0,
                    request_id=f"request_{suffix}",
                    response_id=f"response_{suffix}",
                    requested_at=timestamp,
                    responded_at=timestamp,
                    latency_ms=0,
                    outcome=ProviderTransportOutcome.ACCEPTED,
                    provider_status="in_process",
                    retryable=False,
                    usage={"validated_objects": 1},
                ),
            )
        )
        observations = ProviderObservationalProvenance(
            request_id=f"request_{suffix}",
            response_id=f"response_{suffix}",
            requested_at=timestamp,
            responded_at=timestamp,
            latency_ms=0,
            usage={"validated_objects": 1},
            retry_count=0,
            attempts=attempts,
            transport_metadata={"network_access": False, "transport": "in_process"},
        )
        return create_provider_result(
            result_type=result_type,
            action=action,
            output=output,
            provider_identity=self.provider_identity,
            model_snapshot=self.model_snapshot,
            observations=observations,
            call_context=call_context,
        )
