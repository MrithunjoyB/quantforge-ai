"""Immutable, strict, versioned schemas for the QuantForge tribunal domain."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from quantforge.serialization.canonical import canonical_decimal, canonical_sha256

SCHEMA_VERSION: Literal["1.0"] = "1.0"
IDENTIFIER_PATTERN = r"^[a-z][a-z0-9_-]{2,127}$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
UNSTRUCTURED_NUMBER = re.compile(
    r"(?<![\w])[-+]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][-+]?\d+)?%?(?![\w])"
)
NONFINITE_NUMBER = re.compile(r"(?<![\w])(?:nan|[-+]?inf(?:inity)?)(?![\w])", re.IGNORECASE)


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


def _safe_structured_location(value: str) -> str:
    if (
        len(value) > 512
        or not value.startswith("/")
        or "//" in value
        or ".." in value.split("/")
        or any(unicodedata.category(character) == "Cc" for character in value)
    ):
        raise ValueError("structured location must be a normalized JSON pointer")
    return value


def _no_unstructured_number(value: str) -> str:
    if UNSTRUCTURED_NUMBER.search(value) or NONFINITE_NUMBER.search(value):
        raise ValueError("numerical text must use structured numerical-fact references")
    return value


def _safe_text(value: str) -> str:
    if any(
        unicodedata.category(character) == "Cc" and character not in {"\n", "\t"}
        for character in value
    ):
        raise ValueError("text contains a forbidden control character")
    return unicodedata.normalize("NFC", value)


def _bounded_decimal(value: Decimal) -> Decimal:
    canonical_decimal(value)
    return Decimal(0) if value.is_zero() else value


Timestamp = Annotated[datetime, AfterValidator(_aware_utc)]
Identifier = Annotated[str, Field(pattern=IDENTIFIER_PATTERN)]
Sha256 = Annotated[str, Field(pattern=SHA256_PATTERN)]
SafeArtifactPath = Annotated[str, AfterValidator(_safe_artifact_path)]
StructuredLocation = Annotated[str, AfterValidator(_safe_structured_location)]
NarrativeText = Annotated[
    str,
    Field(min_length=1, max_length=4000),
    AfterValidator(_safe_text),
    AfterValidator(_no_unstructured_number),
]
BoundedDecimal = Annotated[Decimal, AfterValidator(_bounded_decimal)]
Unit = Literal["basis_points", "fraction", "percent", "currency_units", "count", "days", "ratio"]
type JsonValue = str | int | bool | None | Decimal | list[JsonValue] | dict[str, JsonValue]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
        validate_default=True,
    )

    @classmethod
    def model_construct(cls, _fields_set: set[str] | None = None, **values: Any) -> Self:
        """Disable Pydantic's unchecked construction escape hatch for domain objects."""

        del _fields_set
        return cls.model_validate(values)

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
        """Return a fully revalidated immutable copy; `deep` is retained for API compatibility."""

        del deep
        data = self.model_dump(mode="python")
        data.update(update or {})
        return type(self).model_validate(data)


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


class GateStatus(StrEnum):
    PASS = "pass"  # noqa: S105 - policy gate status, not a credential
    FAIL = "fail"
    UNRESOLVED = "unresolved"


class Sensitivity(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class Stability(StrEnum):
    STABLE = "stable"
    MIXED = "mixed"
    UNSTABLE = "unstable"


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

    @model_validator(mode="after")
    def valid_period(self) -> Self:
        try:
            start = date.fromisoformat(self.start_date)
            end = date.fromisoformat(self.end_date)
        except ValueError as error:
            raise ValueError("claim scope dates must use ISO calendar dates") from error
        if start > end:
            raise ValueError("claim scope start date must not follow end date")
        if len(self.asset_classes) != len(set(self.asset_classes)) or len(self.universe) != len(
            set(self.universe)
        ):
            raise ValueError("claim scope collections must be unique")
        if any(not item.strip() for item in (*self.asset_classes, *self.universe)):
            raise ValueError("claim scope collections cannot contain empty values")
        return self


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
    unit: Unit
    calculation: NarrativeText
    primary: bool


class DataRequirement(StrictModel):
    requirement_id: Identifier
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    description: NarrativeText
    lineage_required: bool = True
    synthetic_allowed: bool = True


class Rate(StrictModel):
    value: BoundedDecimal
    unit: Literal["basis_points", "fraction", "percent"]

    @model_validator(mode="after")
    def valid_cost_rate(self) -> Self:
        upper = {
            "basis_points": Decimal("1000000"),
            "fraction": Decimal("1"),
            "percent": Decimal("100"),
        }[self.unit]
        if self.value < 0 or self.value > upper:
            raise ValueError("execution cost rate is outside its supported range")
        return self


class Money(StrictModel):
    amount: BoundedDecimal
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]

    @model_validator(mode="after")
    def positive_amount(self) -> Self:
        if self.amount <= 0:
            raise ValueError("starting capital must be positive")
        return self


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

    @model_validator(mode="after")
    def scientific_identity(self) -> Self:
        identifiers = [
            self.primary_hypothesis.hypothesis_id,
            self.null_hypothesis.hypothesis_id,
            *(item.metric_id for item in self.metrics),
            *(item.requirement_id for item in self.data_requirements),
            *(item.assumption_id for item in self.execution_assumptions),
            *(item.benchmark_id for item in self.benchmarks),
            *(item.criterion_id for item in self.failure_criteria),
        ]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("proposal component identifiers must be unique")
        if not any(metric.primary for metric in self.metrics):
            raise ValueError("proposal requires at least one primary metric")
        return self


class EvidenceReference(StrictModel):
    evidence_id: Identifier
    numeric_fact_ids: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def unique_facts(self) -> Self:
        if len(self.numeric_fact_ids) != len(set(self.numeric_fact_ids)):
            raise ValueError("numeric fact references must be unique")
        return self


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

    @model_validator(mode="after")
    def approved_review_is_complete(self) -> Self:
        checks = (
            self.causality_checked,
            self.leakage_checked,
            self.benchmark_parity_checked,
            self.execution_assumptions_checked,
            self.multiple_testing_checked,
            self.evaluable,
        )
        if self.decision is ReviewDecision.APPROVED and not all(checks):
            raise ValueError("approved methodology review requires every governance check")
        if self.decision is ReviewDecision.APPROVED and any(
            finding.severity is FindingSeverity.CRITICAL and not finding.resolved
            for finding in self.findings
        ):
            raise ValueError("approved methodology cannot retain an unresolved critical finding")
        return self


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
        if self.proposal.experiment_id != self.experiment_id:
            raise ValueError("proposal and constitution experiment mismatch")
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
        normalized_keys = tuple(key.casefold().replace("/", ".") for key in self.changes)
        nested_keys: list[str] = []

        def collect_keys(value: JsonValue) -> None:
            if isinstance(value, dict):
                for key, nested in value.items():
                    nested_keys.append(key.casefold().replace("/", "."))
                    collect_keys(nested)
            elif isinstance(value, list):
                for nested in value:
                    collect_keys(nested)

        collect_keys(self.changes)
        forbidden_fragments = ("primary_hypothesis", "null_hypothesis", "failure_criteria")
        if any(
            fragment in key
            for key in (*normalized_keys, *nested_keys)
            for fragment in forbidden_fragments
        ):
            raise ValueError("amendments cannot rewrite primary or null hypotheses")
        permitted_prefixes = {
            AmendmentClassification.ADMINISTRATIVE: ("metadata.", "display_label"),
            AmendmentClassification.EXPLORATORY: ("exploratory.",),
            AmendmentClassification.REVIEWER_REQUESTED: ("follow_up.", "robustness."),
        }
        if not self.changes or any(
            not key.startswith(permitted_prefixes[self.classification]) for key in normalized_keys
        ):
            raise ValueError("amendment changes do not match their classification")
        permitted_roles = {
            AmendmentClassification.ADMINISTRATIVE: {
                RoleName.RESEARCHER,
                RoleName.HUMAN_APPROVER,
                RoleName.SYSTEM,
            },
            AmendmentClassification.EXPLORATORY: {RoleName.RESEARCHER},
            AmendmentClassification.REVIEWER_REQUESTED: {
                RoleName.METHODOLOGY_AUDITOR,
                RoleName.STATISTICAL_REVIEWER,
                RoleName.ADVERSARIAL_REVIEWER,
                RoleName.REPRODUCIBILITY_REVIEWER,
            },
        }
        if self.author_role not in permitted_roles[self.classification]:
            raise ValueError("amendment author is not permitted for the classification")
        payload = self.model_dump(mode="python", exclude={"amendment_hash"})
        if canonical_sha256(payload) != self.amendment_hash:
            raise ValueError("amendment hash mismatch")
        return self


class NumericFact(StrictModel):
    fact_id: Identifier
    name: str = Field(min_length=1, max_length=120)
    value: BoundedDecimal
    unit: Unit


class EvidenceObject(StrictModel):
    evidence_id: Identifier
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    evidence_type: Identifier
    case_id: Identifier
    claim_ids: tuple[Identifier, ...] = Field(min_length=1)
    experiment_id: Identifier
    constitution_hash: Sha256
    source_adapter: Identifier
    source_artifact: SafeArtifactPath
    source_artifact_sha256: Sha256
    structured_location: StructuredLocation | None = None
    content_sha256: Sha256
    created_at: Timestamp
    validation_status: ValidationStatus
    validation_method: str = Field(min_length=1, max_length=200)
    content: dict[str, JsonValue]
    numeric_facts: tuple[NumericFact, ...]
    units: tuple[Unit, ...]
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
        if len(self.claim_ids) != len(set(self.claim_ids)):
            raise ValueError("duplicate evidence claim identifier")
        fact_units = {fact.unit for fact in self.numeric_facts}
        if len(self.units) != len(set(self.units)) or set(self.units) != fact_units:
            raise ValueError("evidence units must exactly match numeric fact units")
        content_facts = self.content.get("facts")
        expected_facts = {
            fact.fact_id: canonical_decimal(fact.value) for fact in self.numeric_facts
        }
        if content_facts != expected_facts:
            raise ValueError("structured numeric facts do not match hashed evidence content")
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
    robustness_status: GateStatus
    cost_sensitivity: Sensitivity
    parameter_stability: Stability
    regime_stability: Stability
    concentration_risk: Sensitivity
    findings: tuple[ReviewerFinding, ...]
    reviewed_at: Timestamp

    @model_validator(mode="after")
    def challenge_summary_is_consistent(self) -> Self:
        statuses = {challenge.status for challenge in self.challenges}
        expected = (
            GateStatus.FAIL
            if ChallengeStatus.FAILED in statuses
            else GateStatus.UNRESOLVED
            if ChallengeStatus.UNRESOLVED in statuses
            else GateStatus.PASS
        )
        if self.robustness_status is not expected:
            raise ValueError("adversarial robustness summary contradicts challenge statuses")
        failed_cost = any(
            challenge.challenge_type is ChallengeType.COST
            and challenge.status is ChallengeStatus.FAILED
            for challenge in self.challenges
        )
        if failed_cost != (self.cost_sensitivity is Sensitivity.HIGH):
            raise ValueError("cost sensitivity contradicts the cost challenge")
        return self


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

    @model_validator(mode="after")
    def verified_review_is_complete(self) -> Self:
        checks = (
            self.configuration_verified,
            self.manifests_verified,
            self.hashes_verified,
            self.software_identity_verified,
            self.data_lineage_verified,
            self.evidence_complete,
        )
        if self.status is ReproducibilityStatus.VERIFIED and not all(checks):
            raise ValueError("verified reproducibility requires every reconstruction check")
        return self


class VerdictEligibility(StrictModel):
    eligibility_id: Identifier
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    policy_version: Literal["1.0"] = "1.0"
    verdict: Verdict
    decisive_reasons: tuple[str, ...] = Field(min_length=1)
    decisive_evidence: tuple[EvidenceReference, ...] = Field(min_length=1)
    contradictory_evidence: tuple[EvidenceReference, ...] = ()
    computed_at: Timestamp

    @model_validator(mode="after")
    def evidence_sets_are_consistent(self) -> Self:
        decisive = {reference.evidence_id for reference in self.decisive_evidence}
        contradictory = {reference.evidence_id for reference in self.contradictory_evidence}
        if len(decisive) != len(self.decisive_evidence):
            raise ValueError("decisive evidence references must be unique")
        if len(contradictory) != len(self.contradictory_evidence):
            raise ValueError("contradictory evidence references must be unique")
        if not contradictory.issubset(decisive):
            raise ValueError("contradictory evidence must also be decisive evidence")
        return self


class AuditEvent(StrictModel):
    event_id: Identifier
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    sequence: Annotated[int, Field(ge=1)]
    timestamp: Timestamp
    case_id: Identifier
    workflow_state: WorkflowState
    actor: RoleName
    action: Identifier
    payload: JsonValue
    payload_hash: Sha256
    previous_event_hash: Sha256
    current_event_hash: Sha256


class ChairExplanation(StrictModel):
    explanation_id: Identifier
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    computed_verdict: Verdict
    summary: NarrativeText
    decisive_evidence: tuple[EvidenceReference, ...] = Field(min_length=1)
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
        state_index = list(WorkflowState).index(self.state)
        staged_fields: tuple[tuple[int, str, object], ...] = (
            (1, "proposal", self.proposal),
            (2, "methodology_review", self.methodology_review),
            (3, "human_approval", self.human_approval),
            (4, "constitution", self.constitution),
            (6, "statistical_review", self.statistical_review),
            (7, "adversarial_review", self.adversarial_review),
            (9, "reproducibility_review", self.reproducibility_review),
            (10, "verdict_eligibility", self.verdict_eligibility),
            (11, "chair_explanation", self.chair_explanation),
        )
        for introduced_at, name, value in staged_fields:
            if state_index >= introduced_at and value is None:
                raise ValueError(f"workflow state requires {name}")
            if state_index < introduced_at and value is not None:
                raise ValueError(f"workflow state cannot contain future field {name}")
        if state_index >= 5 and not self.evidence_ids:
            raise ValueError("executed experiment requires evidence identifiers")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("case evidence identifiers must be unique")
        if state_index < 5 and self.evidence_ids:
            raise ValueError("evidence identifiers cannot exist before experiment execution")
        if state_index >= 9 and self.follow_up_disposition is None:
            raise ValueError("reproducibility review requires explicit follow-up disposition")
        if state_index < 9 and self.follow_up_disposition is not None:
            raise ValueError("follow-up disposition is premature")
        if self.proposal is not None and self.proposal.claim_id != self.claim.claim_id:
            raise ValueError("proposal and claim identifiers do not match")
        if self.methodology_review is not None and self.proposal is not None:
            if self.methodology_review.experiment_id != self.proposal.experiment_id:
                raise ValueError("methodology review and proposal experiments do not match")
            if state_index >= 3 and self.methodology_review.decision is not ReviewDecision.APPROVED:
                raise ValueError("nonapproved methodology cannot progress")
        if self.human_approval is not None and self.proposal is not None:
            if self.human_approval.experiment_id != self.proposal.experiment_id:
                raise ValueError("approval and proposal experiments do not match")
            if not self.human_approval.approved:
                raise ValueError("workflow progression requires positive human approval")
        if self.constitution is not None:
            if self.constitution.proposal != self.proposal:
                raise ValueError("case constitution does not embed the recorded proposal")
            if self.constitution.human_approval != self.human_approval:
                raise ValueError("case constitution does not embed the recorded approval")
            parent_hash = self.constitution.constitution_hash
            previous_amendment_time = self.constitution.locked_at
            for amendment in self.amendments:
                if amendment.parent_constitution_hash != parent_hash:
                    raise ValueError("amendment lineage parent hash mismatch")
                if amendment.created_at <= previous_amendment_time:
                    raise ValueError("amendment timestamps must be strictly append-only")
                parent_hash = amendment.amendment_hash
                previous_amendment_time = amendment.created_at
        elif self.amendments:
            raise ValueError("amendments require a locked constitution")
        eligibility = self.verdict_eligibility
        if self.chair_explanation and eligibility is None:
            raise ValueError("Chair explanation requires computed verdict eligibility")
        if (
            self.chair_explanation
            and eligibility is not None
            and self.chair_explanation.computed_verdict != eligibility.verdict
        ):
            raise ValueError("Chair cannot alter the computed verdict")
        if self.chair_explanation and eligibility is not None:
            if self.chair_explanation.decisive_evidence != eligibility.decisive_evidence:
                raise ValueError("Chair cannot change decisive policy evidence")
            if self.chair_explanation.contradictory_evidence != eligibility.contradictory_evidence:
                raise ValueError("Chair cannot omit or change contradictory policy evidence")
        timestamps = [self.claim.submitted_at]
        for item in (
            self.proposal,
            self.methodology_review,
            self.human_approval,
            self.constitution,
            self.statistical_review,
            self.adversarial_review,
            self.reproducibility_review,
            self.verdict_eligibility,
            self.chair_explanation,
        ):
            if item is not None:
                timestamp = next(
                    getattr(item, name)
                    for name in (
                        "proposed_at",
                        "reviewed_at",
                        "approved_at",
                        "locked_at",
                        "computed_at",
                        "created_at",
                    )
                    if hasattr(item, name)
                )
                timestamps.append(timestamp)
        if any(later < earlier for earlier, later in pairwise(timestamps)):
            raise ValueError("workflow domain timestamps are not monotonic")
        return self


def validated_model_update(model: StrictModel, **changes: Any) -> Any:
    """Apply an immutable update and rerun all strict field and cross-field validation."""

    data = model.model_dump(mode="python")
    data.update(changes)
    return type(model).model_validate(data)
