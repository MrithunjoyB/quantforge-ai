from __future__ import annotations

from datetime import UTC, datetime
from itertools import product
from typing import Literal

import pytest
from pydantic import ValidationError

from quantforge.domain.models import (
    CorrectedInference,
    EvidenceReference,
    GateStatus,
    ReproducibilityStatus,
    ReviewDecision,
    Sensitivity,
    Stability,
    ValidationStatus,
    Verdict,
)
from quantforge.roles.chair import create_chair_explanation
from quantforge.verdict.policy import VerdictInputs, VerdictPolicy


def _inputs(**updates: object) -> VerdictInputs:
    values: dict[str, object] = {
        "methodology_status": ReviewDecision.APPROVED,
        "primary_experiment_complete": True,
        "evidence_validation_statuses": (ValidationStatus.VALIDATED,),
        "corrected_inference": CorrectedInference.PASS,
        "expected_direction": "positive",
        "effect_direction": "positive",
        "practical_significance": True,
        "robustness_status": GateStatus.PASS,
        "cost_sensitivity": Sensitivity.LOW,
        "parameter_stability": Stability.STABLE,
        "regime_stability": Stability.STABLE,
        "concentration_risk": Sensitivity.LOW,
        "reproducibility_status": ReproducibilityStatus.VERIFIED,
        "unresolved_critical_findings": False,
        "contradictory_evidence": (),
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
        {"effect_direction": "null"},
        {"practical_significance": False},
        {"robustness_status": GateStatus.UNRESOLVED},
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


def test_revision_requested_is_not_a_positive_verdict() -> None:
    result = VerdictPolicy.compute(
        _inputs(methodology_status=ReviewDecision.REVISION_REQUESTED),
        eligibility_id="eligibility_revision",
        computed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert result.verdict is Verdict.INCONCLUSIVE


@pytest.mark.parametrize(
    ("expected_direction", "effect_direction", "expected_verdict"),
    [
        ("negative", "negative", Verdict.SUPPORTED),
        ("two_sided", "negative", Verdict.SUPPORTED),
        ("positive", "negative", Verdict.REJECTED),
        ("negative", "positive", Verdict.REJECTED),
    ],
)
def test_hypothesis_direction_is_part_of_policy(
    expected_direction: Literal["positive", "negative", "two_sided"],
    effect_direction: Literal["positive", "negative", "null", "mixed"],
    expected_verdict: Verdict,
) -> None:
    result = VerdictPolicy.compute(
        _inputs(expected_direction=expected_direction, effect_direction=effect_direction),
        eligibility_id="eligibility_direction",
        computed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert result.verdict is expected_verdict


def test_bounded_policy_truth_table_is_deterministic_and_conservative() -> None:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    reference = EvidenceReference(evidence_id="evidence_policy")
    dimensions = product(
        ReviewDecision,
        ValidationStatus,
        CorrectedInference,
        (("positive", "positive"), ("positive", "negative"), ("positive", "null")),
        GateStatus,
        ReproducibilityStatus,
        (False, True),
    )
    for index, (
        methodology,
        validation,
        inference,
        directions,
        robustness,
        reproducibility,
        contradiction,
    ) in enumerate(dimensions):
        expected_direction, effect_direction = directions
        inputs = _inputs(
            methodology_status=methodology,
            evidence_validation_statuses=(validation,),
            corrected_inference=inference,
            expected_direction=expected_direction,
            effect_direction=effect_direction,
            robustness_status=robustness,
            reproducibility_status=reproducibility,
            contradictory_evidence=(reference,) if contradiction else (),
        )
        first = VerdictPolicy.compute(
            inputs, eligibility_id=f"eligibility_table_{index:04d}", computed_at=timestamp
        )
        second = VerdictPolicy.compute(
            inputs, eligibility_id=f"eligibility_table_{index:04d}", computed_at=timestamp
        )
        assert first == second
        if methodology is ReviewDecision.REJECTED:
            assert first.verdict is Verdict.REJECTED
        elif (
            methodology is ReviewDecision.REVISION_REQUESTED
            or validation is not ValidationStatus.VALIDATED
            or reproducibility is not ReproducibilityStatus.VERIFIED
            or robustness is GateStatus.UNRESOLVED
            or inference is not CorrectedInference.PASS
            or effect_direction == "null"
        ):
            assert first.verdict is Verdict.INCONCLUSIVE
        elif effect_direction == "negative":
            assert first.verdict is Verdict.REJECTED
        elif robustness is GateStatus.FAIL or contradiction:
            assert first.verdict is Verdict.FRAGILE


def test_policy_requires_consistent_decisive_and_contradictory_evidence() -> None:
    with pytest.raises(ValidationError, match="at least 1"):
        _inputs(decisive_evidence=())
    with pytest.raises(ValidationError, match="also be decisive"):
        _inputs(contradictory_evidence=(EvidenceReference(evidence_id="evidence_other"),))


def test_chair_cannot_upgrade_or_change_verdict() -> None:
    eligibility = VerdictPolicy.compute(
        _inputs(unresolved_noncritical_limitations=True),
        eligibility_id="eligibility_chair",
        computed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    def explain(requested_verdict: Verdict) -> object:
        return create_chair_explanation(
            explanation_id="chair_policy",
            eligibility=eligibility,
            requested_verdict=requested_verdict,
            summary="The policy result follows validated gates",
            limitations=("Synthetic evidence has limited external meaning",),
            verdict_change_conditions=("Validated evidence must change a policy gate",),
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    with pytest.raises(PermissionError, match="upgrade"):
        explain(Verdict.SUPPORTED)
    with pytest.raises(ValueError, match="exact"):
        explain(Verdict.FRAGILE)
    explanation = explain(Verdict.PROVISIONALLY_SUPPORTED)
    assert hasattr(explanation, "computed_verdict")
    assert explanation.computed_verdict is Verdict.PROVISIONALLY_SUPPORTED
