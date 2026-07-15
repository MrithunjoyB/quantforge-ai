"""Immutable, strict, versioned schemas for the QuantForge tribunal domain."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from quantforge.serialization.canonical import canonical_sha256

SCHEMA_VERSION: Literal["1.0"] = "1.0"
IDENTIFIER_PATTERN = r"^[a-z][a-z0-9_-]{2,127}$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
UNSTRUCTURED_NUMBER = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:[.,]\d+)?(?:%|\b)")


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _safe_artifact_path(value: str) -> str:
    if not value or "\x00" in value or "\\" in value:
        raise ValueError("artifact path is unsafe")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value.startswith("~"):
        raise ValueError("artifact path must be normalized and relative")
    if any(part in {"", "."} for part in value.split("/")):
        raise ValueError("artifact path contains an ambiguous segment")
    return value


def _no_unstructured_number(value: str) -> str:
    if UNSTRUCTURED_NUMBER.search(value):
        raise ValueError("numerical text must use structured numerical-fact references")
    return value


Timestamp = Annotated[datetime, AfterValidator(_aware_utc)]
Identifier = Annotated[str, Field(pattern=IDENTIFIER_PATTERN)]
Sha256 = Annotated[str, Field(pattern=SHA256_PATTERN)]
SafeArtifactPath = Annotated[str, AfterValidator(_safe_artifact_path)]
NarrativeText = Annotated[
    str, Field(min_length=1, max_length=4000), AfterValidator(_no_unstructured_number)
]
type JsonValue = str | int | bool | None | Decimal | list[JsonValue] | dict[str, JsonValue]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


class WorkflowState(StrEnum):
    CLAIM_RECEIVED = "CLAIM_RECEIVED"
    RESEARCHER_PROTOCOL_PROPOSED = "RESEARCHER_PROTOCOL_PROPOSED"
    METHODOLOGY_REVIEWED = "METHODOLOGY_REVIEWED"
    HUMAN_APPROVAL = "HUMAN_APPROVAL"
    CONSTITUTION_LOCKED = "CONSTITUTION_LOCKED"
    EXPERIMENT_EXECUTED = "EXPERIMENT_EXECUTED"
    STATISTICS_REVIEWED = "STATISTICS_REVIEWED"
    ADVERSARIAL_REVIEWED = "ADVERSARIAL_REVIEWED"
    OPTIONAL_FOLLOW_UP = "OPTIONAL_FOLLOW_UP"
    REPRODUCIBILITY_VERIFIED = "REPRODUCIBILITY_VERIFIED"
    VERDICT_ELIGIBILITY_COMPUTED = "VERDICT_ELIGIBILITY_COMPUTED"
    CHAIR_EXPLANATION = "CHAIR_EXPLANATION"


class RoleName(StrEnum):
    RESEARCHER = "researcher"
    METHODOLOGY_AUDITOR = "methodology_auditor"
    STATISTICAL_REVIEWER = "statistical_reviewer"
    ADVERSARIAL_REVIEWER = "adversarial_reviewer"
    REPRODUCIBILITY_REVIEWER = "reproducibility_reviewer"
    TRIBUNAL_CHAIR = "tribunal_chair"
    HUMAN_APPROVER = "human_approver"
    SYSTEM = "system"


class ReviewDecision(StrEnum):
    APPROVED = "approved"
    REVISION_REQUESTED = "revision_requested"
    REJECTED = "rejected"


class FindingSeverity(StrEnum):
    INFO = "info"
    NONCRITICAL = "noncritical"
    CRITICAL = "critical"


class ValidationStatus(StrEnum):
    VALIDATED = "validated"
    FAILED = "failed"
    PENDING = "pending"


class EvidenceRelationship(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    QUALIFIES = "qualifies"


class AmendmentClassification(StrEnum):
    REVIEWER_REQUESTED = "reviewer_requested"
    EXPLORATORY = "exploratory"
    ADMINISTRATIVE = "administrative"


class ChallengeType(StrEnum):
    COST = "cost"
    REGIME = "regime"
    PARAMETER = "parameter"
    BENCHMARK = "benchmark"
    PLACEBO = "placebo"
    CONCENTRATION = "concentration"
    ROBUSTNESS = "robustness"


class ChallengeStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    UNRESOLVED = "unresolved"


class ReproducibilityStatus(StrEnum):
    VERIFIED = "verified"
    PARTIAL = "partial"
    FAILED = "failed"


class Verdict(StrEnum):
    SUPPORTED = "SUPPORTED"
    PROVISIONALLY_SUPPORTED = "PROVISIONALLY_SUPPORTED"
    INCONCLUSIVE = "INCONCLUSIVE"
    FRAGILE = "FRAGILE"
    REJECTED = "REJECTED"


class ClaimScope(StrictModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    asset_classes: tuple[str, ...] = Field(min_length=1)
    universe: tuple[str, ...] = Field(min_length=1)
    start_date: str
    end_date: str
    research_only: Literal[True] = True


class ResearchClaim(StrictModel):
    claim_id: Identifier
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    statement: NarrativeText
    submitted_by: str = Field(min_length=1, max_length=200)
    submitted_at: Timestamp
    scope: ClaimScope


class PrimaryHypothesis(StrictModel):
    hypothesis_id: Identifier
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    statement: NarrativeText
    expected_direction: Literal["positive", "negative", "two_sided"]


class NullHypothesis(StrictModel):
    hypothesis_id: Identifier
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    statement: NarrativeText


class MetricDefinition(StrictModel):
    metric_id: Identifier
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    name: str = Field(min_length=1, max_length=100)
    unit: str = Field(min_length=1, max_length=50)
    calculation: NarrativeText
    primary: bool


class DataRequirement(StrictModel):
    requirement_id: Identifier
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    description: NarrativeText
    lineage_required: bool = True
    synthetic_allowed: bool = True


class Rate(StrictModel):
    value: Decimal
    unit: Literal["basis_points", "fraction", "percent"]


class Money(StrictModel):
    amount: Decimal
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


class ExecutionAssumption(StrictModel):
    assumption_id: Identifier
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    description: NarrativeText
    commission: Rate
    slippage: Rate
    starting_capital: Money


class BenchmarkDefinition(StrictModel):
    benchmark_id: Identifier
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    name: str = Field(min_length=1, max_length=120)
    parity_rule: NarrativeText


class FailureCriterion(StrictModel):
    criterion_id: Identifier
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    description: NarrativeText
    decisive: bool = True


class ExperimentProposal(StrictModel):
    experiment_id: Identifier
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    claim_id: Identifier
    primary_hypothesis: PrimaryHypothesis
    null_hypothesis: NullHypothesis
    metrics: tuple[MetricDefinition, ...] = Field(min_length=1)
    data_requirements: tuple[DataRequirement, ...] = Field(min_length=1)
    execution_assumptions: tuple[ExecutionAssumption, ...] = Field(min_length=1)
    benchmarks: tuple[BenchmarkDefinition, ...] = Field(min_length=1)
    periods: tuple[str, ...] = Field(min_length=1)
    exclusions: tuple[str, ...]
    failure_criteria: tuple[FailureCriterion, ...] = Field(min_length=1)
    proposed_at: Timestamp


class EvidenceReference(StrictModel):
    evidence_id: Identifier
    numeric_fact_ids: tuple[Identifier, ...] = ()


class ReviewerFinding(StrictModel):
    finding_id: Identifier
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    severity: FindingSeverity
    summary: NarrativeText
    evidence_references: tuple[EvidenceReference, ...] = ()
    resolved: bool = False


class MethodologyReview(StrictModel):
    review_id: Identifier
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    experiment_id: Identifier
    decision: ReviewDecision
    causality_checked: bool
    leakage_checked: bool
    benchmark_parity_checked: bool
    execution_assumptions_checked: bool
    multiple_testing_checked: bool
    evaluable: bool
    findings: tuple[ReviewerFinding, ...]
    reviewed_at: Timestamp


class HumanApproval(StrictModel):
    approval_id: Identifier
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    experiment_id: Identifier
    approved: bool
    approver: str = Field(min_length=1, max_length=200)
    approved_at: Timestamp
    proposal_hash: Sha256


class ExperimentConstitution(StrictModel):
    constitution_id: Identifier
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    experiment_id: Identifier
    proposal: ExperimentProposal
    human_approval: HumanApproval
    locked_at: Timestamp
    constitution_hash: Sha256

    @model_validator(mode="after")
    def integrity(self) -> Self:
        if not self.human_approval.approved:
            raise ValueError("constitution requires explicit human approval")
        if self.human_approval.experiment_id != self.experiment_id:
            raise ValueError("approval and constitution experiment mismatch")
        if self.human_approval.proposal_hash != canonical_sha256(self.proposal):
            raise ValueError("approval does not bind the proposal")
        payload = self.model_dump(mode="python", exclude={"constitution_hash"})
        if canonical_sha256(payload) != self.constitution_hash:
            raise ValueError("constitution hash mismatch")
        return self


class ConstitutionAmendment(StrictModel):
    amendment_id: Identifier
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    classification: AmendmentClassification
    author_role: RoleName
    reason: NarrativeText
    changes: dict[str, JsonValue]
    created_at: Timestamp
    parent_constitution_hash: Sha256
    amendment_hash: Sha256

    @model_validator(mode="after")
    def integrity(self) -> Self:
        forbidden = {"primary_hypothesis", "null_hypothesis", "proposal.primary_hypothesis"}
        if forbidden.intersection(self.changes):
            raise ValueError("amendments cannot rewrite primary or null hypotheses")
        payload = self.model_dump(mode="python", exclude={"amendment_hash"})
        if canonical_sha256(payload) != self.amendment_hash:
            raise ValueError("amendment hash mismatch")
        return self


class NumericFact(StrictModel):
    fact_id: Identifier
    name: str = Field(min_length=1, max_length=120)
    value: Decimal
    unit: str = Field(min_length=1, max_length=50)


class EvidenceObject(StrictModel):
    evidence_id: Identifier
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    evidence_type: Identifier
    claim_ids: tuple[Identifier, ...] = Field(min_length=1)
    experiment_id: Identifier
    constitution_hash: Sha256
    source_adapter: Identifier
    source_artifact: SafeArtifactPath
    structured_location: str | None = None
    content_sha256: Sha256
    created_at: Timestamp
    validation_status: ValidationStatus
    validation_method: str = Field(min_length=1, max_length=200)
    content: dict[str, JsonValue]
    numeric_facts: tuple[NumericFact, ...]
    units: tuple[str, ...]
    assumptions: tuple[NarrativeText, ...]
    limitations: tuple[NarrativeText, ...]
    relationship: EvidenceRelationship
    provenance: dict[str, JsonValue]

    @model_validator(mode="after")
    def integrity(self) -> Self:
        if canonical_sha256(self.content) != self.content_sha256:
            raise ValueError("evidence content hash mismatch")
        fact_ids = [fact.fact_id for fact in self.numeric_facts]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("duplicate numeric fact identifier")
        return self


class CorrectedInference(StrEnum):
    PASS = "pass"  # noqa: S105 - inference status, not a credential
    FAIL = "fail"
    UNRESOLVED = "unresolved"


class StatisticalReview(StrictModel):
    review_id: Identifier
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    effect_direction: Literal["positive", "negative", "null", "mixed"]
    corrected_inference: CorrectedInference
    practical_significance: bool
    findings: tuple[ReviewerFinding, ...]
    sample_limitations: tuple[NarrativeText, ...]
    reviewed_at: Timestamp


class AdversarialChallenge(StrictModel):
    challenge_id: Identifier
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    challenge_type: ChallengeType
    description: NarrativeText
    status: ChallengeStatus
    evidence_references: tuple[EvidenceReference, ...]


class AdversarialReview(StrictModel):
    review_id: Identifier
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    challenges: tuple[AdversarialChallenge, ...] = Field(min_length=1)
    findings: tuple[ReviewerFinding, ...]
    reviewed_at: Timestamp


class ReproducibilityReview(StrictModel):
    review_id: Identifier
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    status: ReproducibilityStatus
    configuration_verified: bool
    manifests_verified: bool
    hashes_verified: bool
    software_identity_verified: bool
    data_lineage_verified: bool
    evidence_complete: bool
    reconstruction_status: str = Field(min_length=1, max_length=100)
    findings: tuple[ReviewerFinding, ...]
    reviewed_at: Timestamp


class VerdictEligibility(StrictModel):
    eligibility_id: Identifier
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    policy_version: Literal["1.0"] = "1.0"
    verdict: Verdict
    decisive_reasons: tuple[str, ...] = Field(min_length=1)
    decisive_evidence: tuple[EvidenceReference, ...]
    computed_at: Timestamp


class AuditEvent(StrictModel):
    event_id: Identifier
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    sequence: Annotated[int, Field(ge=1)]
    timestamp: Timestamp
    case_id: Identifier
    workflow_state: WorkflowState
    actor: RoleName
    action: Identifier
    payload_hash: Sha256
    previous_event_hash: Sha256
    current_event_hash: Sha256


class ChairExplanation(StrictModel):
    explanation_id: Identifier
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    computed_verdict: Verdict
    summary: NarrativeText
    decisive_evidence: tuple[EvidenceReference, ...]
    contradictory_evidence: tuple[EvidenceReference, ...]
    limitations: tuple[NarrativeText, ...]
    verdict_change_conditions: tuple[NarrativeText, ...] = Field(min_length=1)
    created_at: Timestamp


class TribunalCase(StrictModel):
    case_id: Identifier
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    state: WorkflowState
    claim: ResearchClaim
    proposal: ExperimentProposal | None = None
    methodology_review: MethodologyReview | None = None
    human_approval: HumanApproval | None = None
    constitution: ExperimentConstitution | None = None
    amendments: tuple[ConstitutionAmendment, ...] = ()
    evidence_ids: tuple[Identifier, ...] = ()
    statistical_review: StatisticalReview | None = None
    adversarial_review: AdversarialReview | None = None
    follow_up_disposition: Literal["completed", "skipped"] | None = None
    reproducibility_review: ReproducibilityReview | None = None
    verdict_eligibility: VerdictEligibility | None = None
    chair_explanation: ChairExplanation | None = None

    @model_validator(mode="after")
    def governed_visibility(self) -> Self:
        if self.constitution is None and (
            self.evidence_ids or self.statistical_review or self.adversarial_review
        ):
            raise ValueError("results cannot exist before constitution lock")
        eligibility = self.verdict_eligibility
        if self.chair_explanation and eligibility is None:
            raise ValueError("Chair explanation requires computed verdict eligibility")
        if (
            self.chair_explanation
            and eligibility is not None
            and self.chair_explanation.computed_verdict != eligibility.verdict
        ):
            raise ValueError("Chair cannot alter the computed verdict")
        return self


def validated_model_update(model: StrictModel, **changes: Any) -> Any:
    """Apply an immutable update and rerun all strict field and cross-field validation."""

    data = model.model_dump(mode="python")
    data.update(changes)
    return type(model).model_validate(data)
