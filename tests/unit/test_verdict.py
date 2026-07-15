from __future__ import annotations

from datetime import UTC, datetime

import pytest

from quantforge.domain.models import (
    CorrectedInference,
    EvidenceReference,
    ReproducibilityStatus,
    ReviewDecision,
    ValidationStatus,
    Verdict,
)
from quantforge.roles.chair import create_chair_explanation
from quantforge.verdict.policy import (
    GateStatus,
    Sensitivity,
    Stability,
    VerdictInputs,
    VerdictPolicy,
)


def _inputs(**updates: object) -> VerdictInputs:
    values: dict[str, object] = {
        "methodology_status": ReviewDecision.APPROVED,
        "primary_experiment_complete": True,
        "evidence_validation_statuses": (ValidationStatus.VALIDATED,),
        "corrected_inference": CorrectedInference.PASS,
        "effect_direction": "positive",
        "practical_significance": True,
        "robustness_status": GateStatus.PASS,
        "cost_sensitivity": Sensitivity.LOW,
        "parameter_stability": Stability.STABLE,
        "regime_stability": Stability.STABLE,
        "concentration_risk": Sensitivity.LOW,
        "reproducibility_status": ReproducibilityStatus.VERIFIED,
        "unresolved_critical_findings": False,
        "contradictory_evidence": False,
        "unresolved_noncritical_limitations": False,
        "decisive_evidence": (EvidenceReference(evidence_id="evidence_policy"),),
    }
    values.update(updates)
    return VerdictInputs.model_validate(values)


@pytest.mark.parametrize(
    "inputs, expected",
    [
        (_inputs(), Verdict.SUPPORTED),
        (
            _inputs(unresolved_noncritical_limitations=True),
            Verdict.PROVISIONALLY_SUPPORTED,
        ),
        (_inputs(reproducibility_status=ReproducibilityStatus.FAILED), Verdict.INCONCLUSIVE),
        (_inputs(robustness_status=GateStatus.FAIL), Verdict.FRAGILE),
        (_inputs(methodology_status=ReviewDecision.REJECTED), Verdict.REJECTED),
    ],
)
def test_all_verdict_classes(inputs: VerdictInputs, expected: Verdict) -> None:
    eligibility = VerdictPolicy.compute(
        inputs,
        eligibility_id=f"eligibility_{expected.value.lower()}",
        computed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert eligibility.verdict is expected


@pytest.mark.parametrize(
    "updates",
    [
        {"primary_experiment_complete": False},
        {"evidence_validation_statuses": (ValidationStatus.FAILED,)},
        {"corrected_inference": CorrectedInference.UNRESOLVED},
        {"effect_direction": "negative"},
        {"practical_significance": False},
    ],
)
def test_inconclusive_gates(updates: dict[str, object]) -> None:
    result = VerdictPolicy.compute(
        _inputs(**updates),
        eligibility_id="eligibility_inconclusive_gate",
        computed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert result.verdict is Verdict.INCONCLUSIVE


@pytest.mark.parametrize(
    "updates",
    [
        {"cost_sensitivity": Sensitivity.HIGH},
        {"parameter_stability": Stability.UNSTABLE},
        {"regime_stability": Stability.UNSTABLE},
        {"concentration_risk": Sensitivity.HIGH},
    ],
)
def test_fragility_gates(updates: dict[str, object]) -> None:
    result = VerdictPolicy.compute(
        _inputs(**updates),
        eligibility_id="eligibility_fragility_gate",
        computed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert result.verdict is Verdict.FRAGILE


def test_unresolved_critical_finding_rejects() -> None:
    result = VerdictPolicy.compute(
        _inputs(unresolved_critical_findings=True),
        eligibility_id="eligibility_critical",
        computed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert result.verdict is Verdict.REJECTED


def test_chair_cannot_upgrade_or_change_verdict() -> None:
    eligibility = VerdictPolicy.compute(
        _inputs(unresolved_noncritical_limitations=True),
        eligibility_id="eligibility_chair",
        computed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    common = {
        "explanation_id": "chair_policy",
        "eligibility": eligibility,
        "summary": "The policy result follows validated gates",
        "contradictory_evidence": (),
        "limitations": ("Synthetic evidence has limited external meaning",),
        "verdict_change_conditions": ("Validated evidence must change a policy gate",),
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    with pytest.raises(PermissionError, match="upgrade"):
        create_chair_explanation(requested_verdict=Verdict.SUPPORTED, **common)
    with pytest.raises(ValueError, match="exact"):
        create_chair_explanation(requested_verdict=Verdict.FRAGILE, **common)
    explanation = create_chair_explanation(
        requested_verdict=Verdict.PROVISIONALLY_SUPPORTED, **common
    )
    assert explanation.computed_verdict is Verdict.PROVISIONALLY_SUPPORTED
