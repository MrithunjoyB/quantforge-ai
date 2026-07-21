from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from quantforge.evaluation.adapters import SingleAgentEvaluationAdapter
from quantforge.evaluation.models import (
    AcceptedEvaluationResponse,
    ArchitectureResult,
    BenchmarkCase,
    EvaluationArchitecture,
    EvaluationFinding,
    FindingClassification,
    ProviderObservation,
    identified,
)
from quantforge.evaluation.providers import EvaluationMockProvider
from quantforge.evaluation.scoring import aggregate_metrics, score_case
from quantforge.evaluation.suite import load_mock_responses, load_suite, select_cases
from quantforge.serialization.canonical import canonical_sha256


def _single(benchmark_id: str) -> tuple[BenchmarkCase, ArchitectureResult]:
    case = select_cases(load_suite(), benchmark_id=benchmark_id)[0]
    fixture = next(
        item for item in load_mock_responses().responses if item.benchmark_id == benchmark_id
    )
    result = SingleAgentEvaluationAdapter().run(
        case, EvaluationMockProvider(case.public_input(), fixture)
    )
    return case, result


def _replace_terminal(
    result: ArchitectureResult, findings: tuple[EvaluationFinding, ...]
) -> ArchitectureResult:
    prior = result.responses[-1]
    output = prior.output.model_copy(update={"findings": findings})
    response = AcceptedEvaluationResponse(
        request_semantic_sha256=prior.request_semantic_sha256,
        output=output,
        observation=prior.observation,
        semantic_sha256=canonical_sha256(
            {
                "request_semantic_sha256": prior.request_semantic_sha256,
                "output": output,
            }
        ),
    )
    values = result.model_dump(mode="python", exclude={"semantic_sha256"})
    values["responses"] = (*result.responses[:-1], response)
    values["final_output"] = output
    return identified(ArchitectureResult, values)


def test_case_scoring_distinguishes_exact_partial_and_missed_detection() -> None:
    case, exact_result = _single("qf-bm-001-look-ahead")
    exact = score_case(case, exact_result)
    finding = exact_result.final_output.findings[0]
    partial_result = _replace_terminal(
        exact_result,
        (finding.model_copy(update={"classification": FindingClassification.REASONABLE_CONCERN}),),
    )
    partial = score_case(case, partial_result)
    missed = score_case(case, _replace_terminal(exact_result, ()))

    assert (exact.exact_true_positives, exact.partial_true_positives, exact.false_negatives) == (
        1,
        0,
        0,
    )
    assert (
        partial.exact_true_positives,
        partial.partial_true_positives,
        partial.false_negatives,
    ) == (0, 1, 0)
    assert missed.false_negatives == 1
    assert exact.detection_credit_earned == case.scoring_rubric.exact_detection_credit
    assert partial.detection_credit_earned == case.scoring_rubric.reasonable_concern_credit
    assert missed.detection_credit_earned == 0


def test_clean_false_positive_and_component_metrics_have_exact_ratios() -> None:
    clean_case, clean_result = _single("qf-bm-024-sound-control")
    source_case, source_result = _single("qf-bm-003-cost-omission")
    source = source_result.final_output.findings[0]
    injected = source.model_copy(
        update={
            "finding_id": "finding_clean_false_positive",
            "evidence_ids": (clean_case.evidence_inventory[0].evidence_id,),
        }
    )
    false_positive_result = _replace_terminal(clean_result, (injected,))
    score = score_case(clean_case, false_positive_result)
    metrics = aggregate_metrics(
        false_positive_result.architecture,
        (clean_case,),
        (false_positive_result,),
        (score,),
        {clean_case.benchmark_id: True},
    )

    assert source_case.expected_minimum_findings
    assert score.clean_false_positive
    assert metrics.clean_case_false_positive_rate.numerator == 1
    assert metrics.clean_case_false_positive_rate.denominator == 1
    assert metrics.clean_case_false_positive_rate.value == Decimal("1")
    assert metrics.defect_true_positive_rate.value is None
    assert metrics.f1 is None
    assert not metrics.live_token_usage_available


def test_scoring_rejects_foreign_results_and_tampered_semantic_identity() -> None:
    first_case, first_result = _single("qf-bm-001-look-ahead")
    second_case, _ = _single("qf-bm-002-survivorship")
    with pytest.raises(ValueError, match="foreign architecture result"):
        score_case(second_case, first_result)

    score = score_case(first_case, first_result)
    values = score.model_dump(mode="python")
    values["false_negatives"] = 1
    with pytest.raises(ValidationError):
        type(score).model_validate(values)


def test_metric_aggregation_rejects_missing_or_foreign_architecture_inputs() -> None:
    case, result = _single("qf-bm-004-stale-execution")
    score = score_case(case, result)
    with pytest.raises(ValueError, match="exactly one result"):
        aggregate_metrics(result.architecture, (case,), (), (), {})

    values = result.model_dump(mode="python", exclude={"semantic_sha256"})
    values["architecture"] = EvaluationArchitecture.PLANNER_REVIEWER
    foreign = identified(ArchitectureResult, values)
    with pytest.raises(ValueError, match="foreign architecture result"):
        aggregate_metrics(result.architecture, (case,), (foreign,), (score,), {})


def test_observational_metadata_cannot_change_semantic_identity_or_scoring() -> None:
    case, result = _single("qf-bm-005-selection-bias")
    response = result.responses[-1]
    live_like_observation = ProviderObservation(
        provider_identity=response.observation.provider_identity,
        model_snapshot=response.observation.model_snapshot,
        endpoint_class=response.observation.endpoint_class,
        request_id="observational-request-id",
        response_id="observational-response-id",
        input_tokens=123,
        output_tokens=45,
        latency_ms=678,
        estimated_cost_usd=Decimal("0.00123"),
    )
    observed_response = AcceptedEvaluationResponse(
        request_semantic_sha256=response.request_semantic_sha256,
        output=response.output,
        observation=live_like_observation,
        semantic_sha256=response.semantic_sha256,
    )
    values = result.model_dump(mode="python", exclude={"semantic_sha256"})
    values["responses"] = (observed_response,)
    values["final_output"] = observed_response.output
    observed_result = identified(ArchitectureResult, values)

    assert observed_result.semantic_sha256 == result.semantic_sha256
    assert score_case(case, observed_result) == score_case(case, result)
