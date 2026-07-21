"""Strict, versioned models for comparative evaluation and code-owned ground truth."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from quantforge.domain.models import Identifier, JsonValue, Sha256, StrictModel, Timestamp
from quantforge.roles.contracts import RoleAction
from quantforge.serialization.canonical import canonical_sha256

EVALUATION_LABEL: Literal["OFFLINE DETERMINISTIC EVALUATION — MOCK PROVIDER"] = (
    "OFFLINE DETERMINISTIC EVALUATION — MOCK PROVIDER"
)


class EvaluationArchitecture(StrEnum):
    SINGLE_AGENT = "single_agent"
    PLANNER_REVIEWER = "planner_reviewer"
    QUANTFORGE_TRIBUNAL = "quantforge_tribunal"


class EvaluationMode(StrEnum):
    OFFLINE_MOCK = "offline_mock"
    LIVE_OPENAI = "live_openai"


class BenchmarkStatus(StrEnum):
    DEFECT = "defect"
    CLEAN = "clean"


class FindingClassification(StrEnum):
    DEMONSTRATED_DEFECT = "demonstrated_defect"
    REASONABLE_CONCERN = "reasonable_concern"
    UNSUPPORTED_SPECULATION = "unsupported_speculation"
    CLEAN_CONTROL = "clean_control"
    AUTHORITY_VIOLATION = "authority_violation"


class DefectKind(StrEnum):
    LOOK_AHEAD_LEAKAGE = "look_ahead_leakage"
    SURVIVORSHIP_BIAS = "survivorship_bias"
    TRANSACTION_COST_OMISSION = "transaction_cost_omission"
    STALE_OR_IMPOSSIBLE_EXECUTION = "stale_or_impossible_execution"
    SELECTION_BIAS = "selection_bias"
    MULTIPLICITY = "multiplicity"
    UNSTABLE_PARAMETERS = "unstable_parameters"
    REGIME_DEPENDENCE = "regime_dependence"
    WEAK_BENCHMARK = "weak_benchmark"
    INSUFFICIENT_POWER = "insufficient_power"
    FABRICATED_NUMERICAL_EVIDENCE = "fabricated_numerical_evidence"
    CONTRADICTORY_EVIDENCE = "contradictory_evidence"
    MISSING_PROVENANCE = "missing_provenance"
    TAMPERED_ARTIFACT = "tampered_artifact"
    CROSS_CASE_SUBSTITUTION = "cross_case_substitution"
    CROSS_REVISION_SUBSTITUTION = "cross_revision_substitution"
    STALE_AFTER_AMENDMENT = "stale_after_amendment"
    PROMPT_INJECTION = "prompt_injection"
    VERDICT_UPGRADE_ATTEMPT = "verdict_upgrade_attempt"
    CONSTITUTION_MUTATION_ATTEMPT = "constitution_mutation_attempt"
    PROVIDER_AUTHORITY_ATTEMPT = "provider_authority_attempt"
    REPRODUCIBILITY_FAILURE = "reproducibility_failure"


class AuthorityAction(StrEnum):
    WRITE_CASE_STORE = "write_case_store"
    INVOKE_ENGINE = "invoke_engine"
    CREATE_TRUSTED_EVIDENCE = "create_trusted_evidence"
    APPROVE_HUMAN = "approve_human"
    MUTATE_CONSTITUTION = "mutate_constitution"
    CHOOSE_VERDICT = "choose_verdict"


class Recommendation(StrEnum):
    ACCEPT = "accept"
    REVISE = "revise"
    REJECT = "reject"
    UNCERTAIN = "uncertain"


class EvaluationStage(StrEnum):
    SINGLE = "single"
    PLANNER = "planner"
    REVIEWER = "reviewer"
    REVISION = "revision"
    TRIBUNAL = "tribunal"


class PublicEvidenceInput(StrictModel):
    evidence_id: Identifier
    kind: Identifier
    summary: str = Field(min_length=1, max_length=2000)
    content: dict[str, JsonValue]
    revision: int = Field(ge=1, le=10_000)
    provenance: dict[str, JsonValue]


class BenchmarkEvidence(PublicEvidenceInput):
    provenance_sha256: Sha256
    semantic_sha256: Sha256

    @model_validator(mode="after")
    def identities_are_exact(self) -> Self:
        if self.provenance_sha256 != canonical_sha256(self.provenance):
            raise ValueError("benchmark evidence provenance hash mismatch")
        values = self.model_dump(mode="python", exclude={"provenance_sha256", "semantic_sha256"})
        if self.semantic_sha256 != canonical_sha256(values):
            raise ValueError("benchmark evidence semantic hash mismatch")
        return self


class PublicBenchmarkInput(StrictModel):
    benchmark_id: Identifier
    case_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    falsifiable_claim: str = Field(min_length=1, max_length=4000)
    evidence_inventory: tuple[PublicEvidenceInput, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def evidence_ids_are_unique(self) -> Self:
        identifiers = [item.evidence_id for item in self.evidence_inventory]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("benchmark evidence identifiers must be unique")
        return self


class FindingExpectation(StrictModel):
    defect_kind: DefectKind
    classification: FindingClassification
    critical: bool
    required_evidence_ids: tuple[Identifier, ...]


class ScoringRubric(StrictModel):
    exact_detection_credit: int = Field(ge=1, le=10)
    reasonable_concern_credit: int = Field(ge=0, le=10)
    unsupported_speculation_credit: Literal[0]
    clean_false_positive_credit: Literal[0]
    evidence_reference_scored_separately: Literal[True]


class GroundTruthInput(StrictModel):
    benchmark_id: Identifier
    expected_status: BenchmarkStatus
    minimum_findings: tuple[FindingExpectation, ...]
    allowed_uncertainty: tuple[str, ...]

    @model_validator(mode="after")
    def status_matches_expectations(self) -> Self:
        if (self.expected_status is BenchmarkStatus.CLEAN) != (not self.minimum_findings):
            raise ValueError("clean status must have no minimum defect findings")
        return self


class BenchmarkCase(StrictModel):
    benchmark_id: Identifier
    case_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    falsifiable_claim: str = Field(min_length=1, max_length=4000)
    evidence_inventory: tuple[BenchmarkEvidence, ...] = Field(min_length=1)
    expected_status: BenchmarkStatus
    expected_minimum_findings: tuple[FindingExpectation, ...]
    allowed_uncertainty: tuple[str, ...]
    prohibited_authority_actions: tuple[AuthorityAction, ...]
    scoring_rubric: ScoringRubric
    public_input_sha256: Sha256
    ground_truth_sha256: Sha256
    provenance_sha256: Sha256
    semantic_sha256: Sha256

    @model_validator(mode="after")
    def case_identities_are_exact(self) -> Self:
        evidence_ids = {item.evidence_id for item in self.evidence_inventory}
        required = {
            evidence_id
            for finding in self.expected_minimum_findings
            for evidence_id in finding.required_evidence_ids
        }
        if not required.issubset(evidence_ids):
            raise ValueError("ground truth references evidence outside the public inventory")
        if (self.expected_status is BenchmarkStatus.CLEAN) != (not self.expected_minimum_findings):
            raise ValueError("benchmark clean status contradicts its minimum findings")
        public = {
            "benchmark_id": self.benchmark_id,
            "case_version": self.case_version,
            "falsifiable_claim": self.falsifiable_claim,
            "evidence_inventory": self.evidence_inventory,
        }
        ground_truth = {
            "benchmark_id": self.benchmark_id,
            "expected_status": self.expected_status,
            "minimum_findings": self.expected_minimum_findings,
            "allowed_uncertainty": self.allowed_uncertainty,
            "prohibited_authority_actions": self.prohibited_authority_actions,
            "scoring_rubric": self.scoring_rubric,
        }
        if self.public_input_sha256 != canonical_sha256(public):
            raise ValueError("benchmark public-input hash mismatch")
        if self.ground_truth_sha256 != canonical_sha256(ground_truth):
            raise ValueError("benchmark ground-truth hash mismatch")
        if self.provenance_sha256 != canonical_sha256(
            tuple(item.provenance_sha256 for item in self.evidence_inventory)
        ):
            raise ValueError("benchmark case provenance hash mismatch")
        semantic = {"public": public, "ground_truth": ground_truth}
        if self.semantic_sha256 != canonical_sha256(semantic):
            raise ValueError("benchmark case semantic hash mismatch")
        return self

    def public_input(self) -> PublicBenchmarkInput:
        """Return a validated copy that structurally excludes all code-owned truth."""

        return PublicBenchmarkInput(
            benchmark_id=self.benchmark_id,
            case_version=self.case_version,
            falsifiable_claim=self.falsifiable_claim,
            evidence_inventory=tuple(
                PublicEvidenceInput.model_validate(
                    item.model_dump(mode="python", include=set(PublicEvidenceInput.model_fields))
                )
                for item in self.evidence_inventory
            ),
        )

    def public_context(self) -> dict[str, object]:
        """Return the only benchmark material eligible for an untrusted provider request."""

        return {
            "benchmark_id": self.benchmark_id,
            "case_version": self.case_version,
            "claim": self.falsifiable_claim,
            "evidence": tuple(
                {
                    "evidence_id": item.evidence_id,
                    "kind": item.kind,
                    "summary": item.summary,
                    "content": item.content,
                    "revision": item.revision,
                    "semantic_sha256": item.semantic_sha256,
                }
                for item in self.evidence_inventory
            ),
        }


class EvaluationFinding(StrictModel):
    finding_id: Identifier
    defect_kind: DefectKind
    classification: FindingClassification
    critical: bool
    summary: str = Field(min_length=1, max_length=2000)
    evidence_ids: tuple[Identifier, ...]

    @model_validator(mode="after")
    def evidence_ids_are_unique(self) -> Self:
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("finding evidence references must be unique")
        return self


class EvaluationProviderOutput(StrictModel):
    benchmark_id: Identifier
    architecture: EvaluationArchitecture
    stage: EvaluationStage
    proposal_summary: str = Field(min_length=1, max_length=2000)
    findings: tuple[EvaluationFinding, ...]
    recommendation: Recommendation
    authority_attempts: tuple[AuthorityAction, ...] = ()
    reproducibility_checks: dict[str, bool]
    refused: bool = False
    failure_kind: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def output_is_consistent(self) -> Self:
        if len(self.authority_attempts) != len(set(self.authority_attempts)):
            raise ValueError("authority attempts must be unique")
        if self.refused != (self.failure_kind is not None):
            raise ValueError("refusal and failure kind must be reported together")
        return self


class EvaluationRequest(StrictModel):
    request_version: Literal["1.0"] = "1.0"
    architecture: EvaluationArchitecture
    stage: EvaluationStage
    benchmark_id: Identifier
    case_version: str
    claim: str
    evidence: tuple[dict[str, JsonValue], ...]
    provider_instructions: tuple[str, ...]
    maximum_context_characters: int = Field(ge=1000, le=1_000_000)
    maximum_output_tokens: int = Field(ge=100, le=100_000)
    context_sha256: Sha256
    request_semantic_sha256: Sha256

    @model_validator(mode="after")
    def request_identity_is_exact(self) -> Self:
        context = {
            "benchmark_id": self.benchmark_id,
            "case_version": self.case_version,
            "claim": self.claim,
            "evidence": self.evidence,
        }
        if self.context_sha256 != canonical_sha256(context):
            raise ValueError("evaluation request context hash mismatch")
        values = self.model_dump(mode="python", exclude={"request_semantic_sha256"})
        if self.request_semantic_sha256 != canonical_sha256(values):
            raise ValueError("evaluation request semantic hash mismatch")
        return self


class ProviderObservation(StrictModel):
    provider_identity: str = Field(min_length=1, max_length=128)
    model_snapshot: str = Field(min_length=1, max_length=200)
    endpoint_class: str = Field(min_length=1, max_length=100)
    request_id: str | None = Field(default=None, max_length=200)
    response_id: str | None = Field(default=None, max_length=200)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    estimated_cost_usd: Decimal | None = Field(default=None, ge=Decimal("0"))
    unavailable_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def unavailable_fields_are_explicit(self) -> Self:
        unavailable = (self.input_tokens, self.output_tokens, self.latency_ms)
        if any(value is None for value in unavailable) and self.unavailable_reason is None:
            raise ValueError("unavailable provider observations require an explicit reason")
        return self


class AcceptedEvaluationResponse(StrictModel):
    request_semantic_sha256: Sha256
    output: EvaluationProviderOutput
    observation: ProviderObservation
    semantic_sha256: Sha256

    @model_validator(mode="after")
    def semantic_identity_is_exact(self) -> Self:
        expected = canonical_sha256(
            {"request_semantic_sha256": self.request_semantic_sha256, "output": self.output}
        )
        if self.semantic_sha256 != expected:
            raise ValueError("accepted evaluation response semantic hash mismatch")
        return self


def _architecture_result_semantic_values(values: Mapping[str, Any]) -> dict[str, Any]:
    semantic = dict(values)
    semantic.pop("semantic_sha256", None)
    responses = semantic.get("responses", ())
    semantic["responses"] = tuple(
        {
            "request_semantic_sha256": (
                response.request_semantic_sha256
                if isinstance(response, AcceptedEvaluationResponse)
                else response["request_semantic_sha256"]
            ),
            "output": (
                response.output
                if isinstance(response, AcceptedEvaluationResponse)
                else response["output"]
            ),
            "semantic_sha256": (
                response.semantic_sha256
                if isinstance(response, AcceptedEvaluationResponse)
                else response["semantic_sha256"]
            ),
        }
        for response in responses
    )
    return semantic


class ArchitectureResult(StrictModel):
    benchmark_id: Identifier
    case_version: str
    architecture: EvaluationArchitecture
    mode: EvaluationMode
    responses: tuple[AcceptedEvaluationResponse, ...] = Field(min_length=1)
    final_output: EvaluationProviderOutput
    authority_attempts: tuple[AuthorityAction, ...]
    authority_successes: tuple[AuthorityAction, ...]
    provider_call_count: int = Field(ge=1, le=100)
    independent_reviewer_count: int = Field(ge=0, le=6)
    retry_count: int = Field(ge=0, le=100)
    store_transition_count: int = Field(ge=0, le=100)
    engine_invocation_count: Literal[0] = 0
    trusted_evidence_created: Literal[False] = False
    human_approval_created_by_provider: Literal[False] = False
    constitution_mutated_by_provider: Literal[False] = False
    verdict_chosen_by_provider: Literal[False] = False
    verdict_upgrade_success: Literal[False] = False
    constitution_mutation_success: Literal[False] = False
    cross_case_acceptance: Literal[False] = False
    cross_revision_acceptance: Literal[False] = False
    duplicate_transition_count: Literal[0] = 0
    schema_valid: bool
    failed: bool
    governed_request_semantic_hashes: tuple[Sha256, ...] = ()
    governed_provider_semantic_hashes: tuple[Sha256, ...] = ()
    tribunal_case_semantic_sha256: Sha256 | None = None
    tribunal_revision: int | None = Field(default=None, ge=1)
    repeat_execution_semantic_sha256: Sha256 | None = None
    deterministic_consistent: bool | None = None
    semantic_sha256: Sha256

    @model_validator(mode="after")
    def architecture_result_is_exact(self) -> Self:
        if self.provider_call_count != len(self.responses):
            raise ValueError("provider call count differs from accepted response inventory")
        if self.final_output != self.responses[-1].output:
            raise ValueError("final output must be the terminal accepted response")
        if not set(self.authority_successes).issubset(self.authority_attempts):
            raise ValueError("authority success must correspond to an attempted action")
        if (self.architecture is EvaluationArchitecture.QUANTFORGE_TRIBUNAL) != (
            self.tribunal_case_semantic_sha256 is not None and self.tribunal_revision is not None
        ):
            raise ValueError("only the tribunal may retain governed case persistence identity")
        if self.architecture is EvaluationArchitecture.QUANTFORGE_TRIBUNAL:
            if (
                len(self.governed_request_semantic_hashes) != self.provider_call_count
                or len(self.governed_provider_semantic_hashes) != self.provider_call_count
            ):
                raise ValueError("tribunal result lacks governed request or provider identities")
        elif self.governed_request_semantic_hashes or self.governed_provider_semantic_hashes:
            raise ValueError("baseline result cannot claim governed tribunal identities")
        if (self.repeat_execution_semantic_sha256 is None) != (
            self.deterministic_consistent is None
        ):
            raise ValueError("repeat identity and consistency status must be recorded together")
        if self.repeat_execution_semantic_sha256 is not None:
            base = self.model_dump(mode="python", exclude={"semantic_sha256"})
            base["repeat_execution_semantic_sha256"] = None
            base["deterministic_consistent"] = None
            observed = canonical_sha256(_architecture_result_semantic_values(base))
            if self.deterministic_consistent != (observed == self.repeat_execution_semantic_sha256):
                raise ValueError("deterministic consistency status contradicts repeat execution")
        values = _architecture_result_semantic_values(self.model_dump(mode="python"))
        if self.semantic_sha256 != canonical_sha256(values):
            raise ValueError("architecture result semantic hash mismatch")
        return self


class CaseScore(StrictModel):
    benchmark_id: Identifier
    architecture: EvaluationArchitecture
    expected_finding_count: int = Field(ge=0)
    exact_true_positives: int = Field(ge=0)
    partial_true_positives: int = Field(ge=0)
    false_negatives: int = Field(ge=0)
    reported_supported_findings: int = Field(ge=0)
    unsupported_speculation_count: int = Field(ge=0)
    clean_false_positive: bool
    critical_expected: int = Field(ge=0)
    critical_detected: int = Field(ge=0)
    evidence_references_valid: int = Field(ge=0)
    evidence_references_total: int = Field(ge=0)
    unsupported_claim_accepted: bool
    fabricated_evidence_accepted: bool
    reproducibility_checks_complete: int = Field(ge=0)
    reproducibility_checks_total: int = Field(ge=0)
    detection_credit_earned: int = Field(ge=0)
    detection_credit_available: int = Field(ge=0)
    semantic_sha256: Sha256

    @model_validator(mode="after")
    def score_identity_is_exact(self) -> Self:
        if self.exact_true_positives + self.partial_true_positives + self.false_negatives != (
            self.expected_finding_count
        ):
            raise ValueError("case detection accounting is incomplete")
        if self.critical_detected > self.critical_expected:
            raise ValueError("critical detection count exceeds expected critical defects")
        values = self.model_dump(mode="python", exclude={"semantic_sha256"})
        if self.semantic_sha256 != canonical_sha256(values):
            raise ValueError("case score semantic hash mismatch")
        return self


class MetricValue(StrictModel):
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    value: Decimal | None

    @model_validator(mode="after")
    def ratio_is_exact(self) -> Self:
        expected = (
            None if self.denominator == 0 else Decimal(self.numerator) / Decimal(self.denominator)
        )
        if self.numerator > self.denominator and self.denominator != 0:
            raise ValueError("bounded metric numerator exceeds denominator")
        if self.value != expected:
            raise ValueError("metric value does not match its exact ratio")
        return self


class ArchitectureMetrics(StrictModel):
    architecture: EvaluationArchitecture
    defect_true_positive_rate: MetricValue
    defect_false_negative_rate: MetricValue
    clean_case_false_positive_rate: MetricValue
    precision: MetricValue
    recall: MetricValue
    f1: Decimal | None
    critical_defect_detection_rate: MetricValue
    unsupported_claim_acceptance_rate: MetricValue
    fabricated_evidence_acceptance_rate: MetricValue
    evidence_reference_precision: MetricValue
    authority_violation_attempt_rate: MetricValue
    authority_violation_success_rate: MetricValue
    verdict_upgrade_success_rate: MetricValue
    constitution_mutation_success_rate: MetricValue
    cross_case_acceptance_rate: MetricValue
    cross_revision_acceptance_rate: MetricValue
    replay_induced_duplicate_transition_rate: MetricValue
    reproducibility_completeness_score: MetricValue
    deterministic_semantic_consistency: MetricValue
    schema_valid_output_rate: MetricValue
    refusal_rate: MetricValue
    failure_rate: MetricValue
    live_token_usage_available: Literal[False]
    live_latency_available: Literal[False]
    live_estimated_cost_available: Literal[False]
    live_observation_unavailable_reason: str


class EvaluationRun(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    evaluation_label: str
    run_id: Identifier
    mode: EvaluationMode
    suite_id: Identifier
    suite_version: str
    suite_semantic_sha256: Sha256
    subset: Literal["full", "judge", "single_case"]
    architectures: tuple[EvaluationArchitecture, ...]
    benchmark_ids: tuple[Identifier, ...]
    provider_identity: str
    model_snapshot: str
    maximum_context_characters: int
    maximum_output_tokens: int
    results: tuple[ArchitectureResult, ...]
    scores: tuple[CaseScore, ...]
    metrics: tuple[ArchitectureMetrics, ...]
    observational_fields_excluded_from_semantic_identity: tuple[str, ...]
    generated_at: Timestamp
    semantic_sha256: Sha256

    @model_validator(mode="after")
    def run_identity_is_exact(self) -> Self:
        expected_pairs = {
            (architecture, benchmark_id)
            for architecture in self.architectures
            for benchmark_id in self.benchmark_ids
        }
        result_pairs = {(item.architecture, item.benchmark_id) for item in self.results}
        score_pairs = {(item.architecture, item.benchmark_id) for item in self.scores}
        if result_pairs != expected_pairs or score_pairs != expected_pairs:
            raise ValueError("evaluation run lacks one result and score per requested pair")
        values = evaluation_run_semantic_values(self.model_dump(mode="python"))
        if self.semantic_sha256 != canonical_sha256(values):
            raise ValueError("evaluation run semantic hash mismatch")
        return self


def evaluation_run_semantic_values(values: Mapping[str, Any]) -> dict[str, Any]:
    """Exclude documented observational fields from an evaluation run identity."""

    semantic = dict(values)
    semantic.pop("generated_at", None)
    semantic.pop("semantic_sha256", None)
    results = semantic.get("results", ())
    semantic["results"] = tuple(
        {
            "architecture": (
                result.architecture
                if isinstance(result, ArchitectureResult)
                else result["architecture"]
            ),
            "benchmark_id": (
                result.benchmark_id
                if isinstance(result, ArchitectureResult)
                else result["benchmark_id"]
            ),
            "semantic_sha256": (
                result.semantic_sha256
                if isinstance(result, ArchitectureResult)
                else result["semantic_sha256"]
            ),
        }
        for result in results
    )
    return semantic


class EvaluationSuite(StrictModel):
    suite_id: Identifier
    suite_version: str
    cases: tuple[BenchmarkCase, ...]
    judge_subset: tuple[Identifier, ...]
    resource_sha256: dict[str, Sha256]
    semantic_sha256: Sha256

    @model_validator(mode="after")
    def suite_identity_is_exact(self) -> Self:
        identifiers = [case.benchmark_id for case in self.cases]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("benchmark identifiers must be unique")
        if len(self.cases) < 24:
            raise ValueError("comparative benchmark suite requires at least twenty-four cases")
        if not set(self.judge_subset).issubset(identifiers):
            raise ValueError("judge subset contains an unknown benchmark identifier")
        if sum(case.expected_status is BenchmarkStatus.CLEAN for case in self.cases) != 1:
            raise ValueError("benchmark suite requires exactly one clean control")
        values = self.model_dump(mode="python", exclude={"semantic_sha256"})
        if self.semantic_sha256 != canonical_sha256(values):
            raise ValueError("benchmark suite semantic hash mismatch")
        return self


class LiveEvaluationPlan(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    suite_semantic_sha256: Sha256
    subset: Literal["full", "judge"]
    case_count: int = Field(ge=1)
    architectures: tuple[EvaluationArchitecture, ...]
    architecture_count: int = Field(ge=1, le=3)
    maximum_call_count: int = Field(ge=1)
    model: str = Field(min_length=1, max_length=200)
    maximum_context_characters: int = Field(ge=1000)
    maximum_input_tokens_estimate: int = Field(ge=1)
    maximum_output_tokens: int = Field(ge=100)
    provider_retry_count: Literal[0]
    input_price_per_million_usd: Decimal = Field(ge=Decimal("0"))
    output_price_per_million_usd: Decimal = Field(ge=Decimal("0"))
    maximum_estimated_cost_usd: Decimal = Field(ge=Decimal("0"))
    requires_official_openai: Literal[True]
    requires_explicit_operator_approval: Literal[True]
    requires_six_call_verification: Literal[True]
    requires_zero_provider_retries: Literal[True]
    plan_sha256: Sha256

    @model_validator(mode="after")
    def plan_identity_is_exact(self) -> Self:
        if self.architecture_count != len(self.architectures):
            raise ValueError("live plan architecture count mismatch")
        if self.maximum_input_tokens_estimate != self.maximum_context_characters * 4:
            raise ValueError("live plan input-token ceiling is not conservative")
        values = self.model_dump(mode="python", exclude={"plan_sha256"})
        if self.plan_sha256 != canonical_sha256(values):
            raise ValueError("live evaluation plan hash mismatch")
        return self


class LiveVerificationReceipt(StrictModel):
    call_count: Literal[6]
    live_output_nondeterministic: Literal[True]
    model: str = Field(min_length=1, max_length=200)
    provider: Literal["openai"]
    semantic_hashes: dict[str, Sha256]
    status: Literal["verified"]

    @model_validator(mode="after")
    def six_roles_are_present(self) -> Self:
        expected = {action.value for action in RoleAction if action in _GOVERNED_ACTIONS}
        if set(self.semantic_hashes) != expected:
            raise ValueError("live verification receipt does not contain all six governed roles")
        return self


_GOVERNED_ACTIONS = frozenset(
    {
        RoleAction.PROPOSE_PROTOCOL,
        RoleAction.REVIEW_METHODOLOGY,
        RoleAction.REVIEW_STATISTICS,
        RoleAction.REQUEST_CHALLENGE,
        RoleAction.REVIEW_REPRODUCIBILITY,
        RoleAction.EXPLAIN_VERDICT,
    }
)


class LiveCheckpoint(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    namespace: Literal["live_openai"]
    plan_sha256: Sha256
    completed_results: tuple[ArchitectureResult, ...]
    calls_consumed: int = Field(ge=0)
    updated_at: datetime


def identified[ModelT: StrictModel](model_type: type[ModelT], values: dict[str, Any]) -> ModelT:
    """Create a model whose final semantic_sha256 binds every other supplied field."""

    data = dict(values)
    for name, field in model_type.model_fields.items():
        if name not in data and name != "semantic_sha256" and not field.is_required():
            data[name] = field.get_default(call_default_factory=True)
    semantic_values = (
        _architecture_result_semantic_values(data) if model_type is ArchitectureResult else data
    )
    data["semantic_sha256"] = canonical_sha256(semantic_values)
    return model_type.model_validate(data)


__all__ = [
    "EVALUATION_LABEL",
    "AcceptedEvaluationResponse",
    "ArchitectureMetrics",
    "ArchitectureResult",
    "AuthorityAction",
    "BenchmarkCase",
    "BenchmarkEvidence",
    "BenchmarkStatus",
    "CaseScore",
    "DefectKind",
    "EvaluationArchitecture",
    "EvaluationFinding",
    "EvaluationMode",
    "EvaluationProviderOutput",
    "EvaluationRequest",
    "EvaluationRun",
    "EvaluationStage",
    "EvaluationSuite",
    "FindingClassification",
    "GroundTruthInput",
    "LiveCheckpoint",
    "LiveEvaluationPlan",
    "LiveVerificationReceipt",
    "MetricValue",
    "ProviderObservation",
    "PublicBenchmarkInput",
    "Recommendation",
    "ScoringRubric",
    "evaluation_run_semantic_values",
    "identified",
]
