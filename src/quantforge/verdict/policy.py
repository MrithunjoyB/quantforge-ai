"""Conservative versioned verdict eligibility policy; no role or LLM chooses verdicts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from quantforge.domain.models import (
    CorrectedInference,
    EvidenceReference,
    ReproducibilityStatus,
    ReviewDecision,
    StrictModel,
    ValidationStatus,
    Verdict,
    VerdictEligibility,
)


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


class VerdictInputs(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    methodology_status: ReviewDecision
    primary_experiment_complete: bool
    evidence_validation_statuses: tuple[ValidationStatus, ...] = Field(min_length=1)
    corrected_inference: CorrectedInference
    effect_direction: Literal["positive", "negative", "null", "mixed"]
    practical_significance: bool
    robustness_status: GateStatus
    cost_sensitivity: Sensitivity
    parameter_stability: Stability
    regime_stability: Stability
    concentration_risk: Sensitivity
    reproducibility_status: ReproducibilityStatus
    unresolved_critical_findings: bool
    contradictory_evidence: bool
    unresolved_noncritical_limitations: bool
    decisive_evidence: tuple[EvidenceReference, ...]


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
            not inputs.primary_experiment_complete
            or not inputs.evidence_validation_statuses
            or any(
                status is not ValidationStatus.VALIDATED
                for status in inputs.evidence_validation_statuses
            )
            or inputs.reproducibility_status is not ReproducibilityStatus.VERIFIED
        ):
            verdict = Verdict.INCONCLUSIVE
            reasons.append("experiment, evidence integrity, or reproducibility gate is incomplete")
        elif (
            inputs.corrected_inference is not CorrectedInference.PASS
            or inputs.effect_direction != "positive"
            or not inputs.practical_significance
        ):
            verdict = Verdict.INCONCLUSIVE
            reasons.append(
                "corrected inference, direction, or practical significance is unresolved"
            )
        elif (
            inputs.robustness_status is GateStatus.FAIL
            or inputs.cost_sensitivity is Sensitivity.HIGH
            or inputs.parameter_stability is Stability.UNSTABLE
            or inputs.regime_stability is Stability.UNSTABLE
            or inputs.concentration_risk is Sensitivity.HIGH
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
            computed_at=computed_at,
        )
