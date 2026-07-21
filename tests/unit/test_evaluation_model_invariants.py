from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from quantforge.evaluation.adapters import SingleAgentEvaluationAdapter
from quantforge.evaluation.live import create_live_plan
from quantforge.evaluation.models import (
    AcceptedEvaluationResponse,
    ArchitectureResult,
    AuthorityAction,
    BenchmarkCase,
    BenchmarkEvidence,
    BenchmarkStatus,
    CaseScore,
    EvaluationArchitecture,
    EvaluationFinding,
    EvaluationProviderOutput,
    EvaluationRequest,
    EvaluationRun,
    EvaluationSuite,
    GroundTruthInput,
    LiveEvaluationPlan,
    LiveVerificationReceipt,
    MetricValue,
    ProviderObservation,
    PublicBenchmarkInput,
    identified,
)
from quantforge.evaluation.providers import EvaluationMockProvider, build_evaluation_request
from quantforge.evaluation.runner import run_offline_evaluation
from quantforge.evaluation.scoring import score_case
from quantforge.evaluation.suite import load_mock_responses, load_suite, select_cases
from quantforge.serialization.canonical import canonical_sha256


def _case_result() -> tuple[BenchmarkCase, ArchitectureResult]:
    case = select_cases(load_suite(), benchmark_id="qf-bm-001-look-ahead")[0]
    fixture = next(
        item for item in load_mock_responses().responses if item.benchmark_id == case.benchmark_id
    )
    result = SingleAgentEvaluationAdapter().run(
        case, EvaluationMockProvider(case.public_input(), fixture)
    )
    return case, result


@pytest.mark.parametrize(
    ("field", "match"),
    (
        ("provenance_sha256", "provenance hash"),
        ("semantic_sha256", "semantic hash"),
    ),
)
def test_benchmark_evidence_hashes_are_exact(field: str, match: str) -> None:
    evidence = load_suite().cases[0].evidence_inventory[0]
    values = evidence.model_dump(mode="python")
    values[field] = "0" * 64
    with pytest.raises(ValidationError, match=match):
        BenchmarkEvidence.model_validate(values)


def test_public_ground_truth_and_finding_models_reject_internal_contradictions() -> None:
    case = load_suite().cases[0]
    public_values = case.public_input().model_dump(mode="python")
    public_values["evidence_inventory"] = (
        public_values["evidence_inventory"][0],
        public_values["evidence_inventory"][0],
    )
    with pytest.raises(ValidationError, match="identifiers must be unique"):
        PublicBenchmarkInput.model_validate(public_values)

    truth = GroundTruthInput(
        benchmark_id=case.benchmark_id,
        expected_status=case.expected_status,
        minimum_findings=case.expected_minimum_findings,
        allowed_uncertainty=case.allowed_uncertainty,
    )
    truth_values = truth.model_dump(mode="python")
    truth_values["expected_status"] = BenchmarkStatus.CLEAN
    with pytest.raises(ValidationError, match="clean status"):
        GroundTruthInput.model_validate(truth_values)

    finding = case.expected_minimum_findings[0]
    evaluation_finding = EvaluationFinding(
        finding_id="finding_test",
        defect_kind=finding.defect_kind,
        classification=finding.classification,
        critical=finding.critical,
        summary="supported",
        evidence_ids=finding.required_evidence_ids,
    )
    with pytest.raises(ValidationError, match="references must be unique"):
        EvaluationFinding.model_validate(
            {
                **evaluation_finding.model_dump(mode="python"),
                "evidence_ids": (finding.required_evidence_ids[0],) * 2,
            }
        )


@pytest.mark.parametrize(
    ("field", "match"),
    (
        ("public_input_sha256", "public-input"),
        ("ground_truth_sha256", "ground-truth"),
        ("provenance_sha256", "provenance"),
        ("semantic_sha256", "semantic"),
    ),
)
def test_benchmark_case_rejects_each_tampered_identity(field: str, match: str) -> None:
    values = load_suite().cases[0].model_dump(mode="python")
    values[field] = "0" * 64
    with pytest.raises(ValidationError, match=match):
        BenchmarkCase.model_validate(values)


def test_benchmark_case_rejects_foreign_truth_references_and_clean_contradiction() -> None:
    case = load_suite().cases[0]
    finding = case.expected_minimum_findings[0].model_copy(
        update={"required_evidence_ids": ("ev-foreign",)}
    )
    values = case.model_dump(mode="python")
    values["expected_minimum_findings"] = (finding,)
    with pytest.raises(ValidationError, match="outside the public inventory"):
        BenchmarkCase.model_validate(values)

    values = case.model_dump(mode="python")
    values["expected_status"] = BenchmarkStatus.CLEAN
    with pytest.raises(ValidationError, match="clean status contradicts"):
        BenchmarkCase.model_validate(values)


def test_provider_output_request_observation_and_response_invariants() -> None:
    case, result = _case_result()
    output = result.final_output
    output_values = output.model_dump(mode="python")
    output_values["authority_attempts"] = (
        AuthorityAction.CHOOSE_VERDICT,
        AuthorityAction.CHOOSE_VERDICT,
    )
    with pytest.raises(ValidationError, match="authority attempts must be unique"):
        EvaluationProviderOutput.model_validate(output_values)
    output_values = output.model_dump(mode="python")
    output_values["refused"] = True
    with pytest.raises(ValidationError, match="refusal and failure"):
        EvaluationProviderOutput.model_validate(output_values)

    request = build_evaluation_request(
        case,
        architecture=EvaluationArchitecture.SINGLE_AGENT,
        stage=output.stage,
    )
    for field, match in (
        ("context_sha256", "context hash"),
        ("request_semantic_sha256", "semantic hash"),
    ):
        request_values = request.model_dump(mode="python")
        request_values[field] = "0" * 64
        with pytest.raises(ValidationError, match=match):
            EvaluationRequest.model_validate(request_values)

    with pytest.raises(ValidationError, match="explicit reason"):
        ProviderObservation(
            provider_identity="provider",
            model_snapshot="model",
            endpoint_class="test",
        )
    response_values = result.responses[-1].model_dump(mode="python")
    response_values["semantic_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="response semantic hash"):
        AcceptedEvaluationResponse.model_validate(response_values)


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        ({"provider_call_count": 2}, "call count"),
        ({"authority_successes": (AuthorityAction.INVOKE_ENGINE,)}, "attempted action"),
        ({"tribunal_case_semantic_sha256": "0" * 64, "tribunal_revision": 1}, "only the tribunal"),
        ({"governed_request_semantic_hashes": ("0" * 64,)}, "baseline result"),
        ({"repeat_execution_semantic_sha256": "0" * 64}, "recorded together"),
    ),
)
def test_architecture_result_rejects_structural_authority_claims(
    mutation: dict[str, object], match: str
) -> None:
    _, result = _case_result()
    values = result.model_dump(mode="python", exclude={"semantic_sha256"})
    values.update(mutation)
    with pytest.raises(ValidationError, match=match):
        identified(ArchitectureResult, values)


def test_score_metric_run_suite_and_live_plan_hash_invariants() -> None:
    case, result = _case_result()
    score = score_case(case, result)
    values = score.model_dump(mode="python")
    values["false_negatives"] = 1
    with pytest.raises(ValidationError, match="accounting"):
        CaseScore.model_validate(values)
    values = score.model_dump(mode="python")
    values["critical_detected"] = score.critical_expected + 1
    with pytest.raises(ValidationError, match="critical detection"):
        CaseScore.model_validate(values)

    with pytest.raises(ValidationError, match="numerator exceeds"):
        MetricValue(numerator=2, denominator=1, value=Decimal("2"))
    with pytest.raises(ValidationError, match="exact ratio"):
        MetricValue(numerator=1, denominator=2, value=Decimal("1"))

    suite = load_suite()
    run = run_offline_evaluation(
        suite,
        (case,),
        architectures=(EvaluationArchitecture.SINGLE_AGENT,),
        subset="single_case",
    )
    run_values = run.model_dump(mode="python")
    run_values["scores"] = ()
    with pytest.raises(ValidationError, match="one result and score"):
        EvaluationRun.model_validate(run_values)
    suite_values = suite.model_dump(mode="python")
    suite_values["judge_subset"] = (*suite.judge_subset, "qf-bm-999-foreign")
    with pytest.raises(ValidationError, match="unknown benchmark"):
        EvaluationSuite.model_validate(suite_values)

    plan = create_live_plan(
        suite,
        subset="judge",
        architectures=(EvaluationArchitecture.SINGLE_AGENT,),
        model="model",
        maximum_context_characters=24_000,
        maximum_output_tokens=2_000,
        input_price_per_million_usd=Decimal("1"),
        output_price_per_million_usd=Decimal("1"),
    )
    plan_values = plan.model_dump(mode="python")
    plan_values["architecture_count"] = 2
    plan_values["plan_sha256"] = canonical_sha256(
        {key: value for key, value in plan_values.items() if key != "plan_sha256"}
    )
    with pytest.raises(ValidationError, match="architecture count"):
        LiveEvaluationPlan.model_validate(plan_values)
    plan_values = plan.model_dump(mode="python")
    plan_values["plan_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="plan hash"):
        LiveEvaluationPlan.model_validate(plan_values)

    with pytest.raises(ValidationError, match="all six governed roles"):
        LiveVerificationReceipt(
            call_count=6,
            live_output_nondeterministic=True,
            model="model",
            provider="openai",
            semantic_hashes={"propose_protocol": "0" * 64},
            status="verified",
        )
