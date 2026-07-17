"""Conservative versioned verdict eligibility policy; no role or LLM chooses verdicts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from quantforge.domain.models import (
    CorrectedInference,
    EvidenceReference,
    GateStatus,
    ReproducibilityStatus,
    ReviewDecision,
    Sensitivity,
    Sha256,
    Stability,
    StrictModel,
    ValidationStatus,
    Verdict,
    VerdictEligibility,
)


class VerdictInputs(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    methodology_status: ReviewDecision
    primary_experiment_complete: bool
    evidence_validation_statuses: tuple[ValidationStatus, ...] = Field(min_length=1)
    corrected_inference: CorrectedInference
    expected_direction: Literal["positive", "negative", "two_sided"]
    effect_direction: Literal["positive", "negative", "null", "mixed"]
    practical_significance: bool
    robustness_status: GateStatus
    cost_sensitivity: Sensitivity
    parameter_stability: Stability
    regime_stability: Stability
    concentration_risk: Sensitivity
    reproducibility_status: ReproducibilityStatus
    unresolved_critical_findings: bool
    contradictory_evidence: tuple[EvidenceReference, ...] = ()
    unresolved_noncritical_limitations: bool
    decisive_evidence: tuple[EvidenceReference, ...] = Field(min_length=1)
    provider_semantic_hashes: tuple[Sha256, ...] = ()

    @model_validator(mode="after")
    def evidence_sets_are_consistent(self) -> VerdictInputs:
        decisive = {reference.evidence_id for reference in self.decisive_evidence}
        contradictory = {reference.evidence_id for reference in self.contradictory_evidence}
        if len(decisive) != len(self.decisive_evidence):
            raise ValueError("decisive evidence references must be unique")
        if len(contradictory) != len(self.contradictory_evidence):
            raise ValueError("contradictory evidence references must be unique")
        if not contradictory.issubset(decisive):
            raise ValueError("contradictory evidence must also be decisive evidence")
        if len(self.provider_semantic_hashes) != len(set(self.provider_semantic_hashes)):
            raise ValueError("provider semantic identities must be unique")
        return self


class VerdictPolicy:
    version: Literal["1.0"] = "1.0"

    @staticmethod
    def compute(
        inputs: VerdictInputs, *, eligibility_id: str, computed_at: datetime
    ) -> VerdictEligibility:
        reasons: list[str] = []
        if (
            inputs.methodology_status is ReviewDecision.REJECTED
            or inputs.unresolved_critical_findings
        ):
            verdict = Verdict.REJECTED
            reasons.append("methodology rejection or unresolved critical finding")
        elif (
            inputs.methodology_status is ReviewDecision.REVISION_REQUESTED
            or not inputs.primary_experiment_complete
            or not inputs.evidence_validation_statuses
            or any(
                status is not ValidationStatus.VALIDATED
                for status in inputs.evidence_validation_statuses
            )
            or inputs.robustness_status is GateStatus.UNRESOLVED
            or inputs.reproducibility_status is not ReproducibilityStatus.VERIFIED
        ):
            verdict = Verdict.INCONCLUSIVE
            reasons.append(
                "methodology, experiment, evidence integrity, or reproducibility gate is incomplete"
            )
        elif (
            inputs.corrected_inference is not CorrectedInference.PASS
            or not inputs.practical_significance
            or inputs.effect_direction in {"null", "mixed"}
        ):
            verdict = Verdict.INCONCLUSIVE
            reasons.append(
                "corrected inference, direction, or practical significance is unresolved"
            )
        elif (
            inputs.expected_direction == "positive" and inputs.effect_direction == "negative"
        ) or (inputs.expected_direction == "negative" and inputs.effect_direction == "positive"):
            verdict = Verdict.REJECTED
            reasons.append("validated effect direction contradicts the primary hypothesis")
        elif (
            inputs.robustness_status is GateStatus.FAIL
            or inputs.cost_sensitivity is Sensitivity.HIGH
            or inputs.parameter_stability is Stability.UNSTABLE
            or inputs.regime_stability is Stability.UNSTABLE
            or inputs.concentration_risk is Sensitivity.HIGH
            or bool(inputs.contradictory_evidence)
        ):
            verdict = Verdict.FRAGILE
            reasons.append(
                "material robustness, sensitivity, stability, or concentration gate failed"
            )
        elif (
            inputs.methodology_status is ReviewDecision.APPROVED
            and inputs.robustness_status is GateStatus.PASS
            and inputs.cost_sensitivity is Sensitivity.LOW
            and inputs.parameter_stability is Stability.STABLE
            and inputs.regime_stability is Stability.STABLE
            and inputs.concentration_risk is Sensitivity.LOW
            and not inputs.contradictory_evidence
            and not inputs.unresolved_noncritical_limitations
        ):
            verdict = Verdict.SUPPORTED
            reasons.append(
                "all strict methodology, evidence, inference, robustness, "
                "and replication gates pass"
            )
        else:
            verdict = Verdict.PROVISIONALLY_SUPPORTED
            reasons.append("primary gates pass with unresolved noncritical limitations")
        return VerdictEligibility(
            eligibility_id=eligibility_id,
            policy_version=VerdictPolicy.version,
            verdict=verdict,
            decisive_reasons=tuple(reasons),
            decisive_evidence=inputs.decisive_evidence,
            contradictory_evidence=inputs.contradictory_evidence,
            computed_at=computed_at,
        )
