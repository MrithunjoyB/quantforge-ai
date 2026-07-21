"""Deterministic execution of one case, one architecture, or a full comparison."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from quantforge.evaluation.adapters import (
    PlannerReviewerEvaluationAdapter,
    QuantForgeTribunalEvaluationAdapter,
    SingleAgentEvaluationAdapter,
)
from quantforge.evaluation.models import (
    EVALUATION_LABEL,
    ArchitectureResult,
    BenchmarkCase,
    EvaluationArchitecture,
    EvaluationMode,
    EvaluationRun,
    EvaluationSuite,
    evaluation_run_semantic_values,
    identified,
)
from quantforge.evaluation.providers import (
    DEFAULT_MAXIMUM_CONTEXT_CHARACTERS,
    DEFAULT_MAXIMUM_OUTPUT_TOKENS,
    EvaluationMockProvider,
)
from quantforge.evaluation.scoring import aggregate_metrics, score_case
from quantforge.evaluation.suite import MockResponseFixture, load_mock_responses
from quantforge.serialization.canonical import canonical_sha256

_OFFLINE_GENERATED_AT = datetime(2099, 4, 1, tzinfo=UTC)
ALL_ARCHITECTURES = tuple(EvaluationArchitecture)


def _execute_once(
    architecture: EvaluationArchitecture,
    case: BenchmarkCase,
    fixture: MockResponseFixture,
    *,
    maximum_context_characters: int,
    maximum_output_tokens: int,
) -> ArchitectureResult:
    provider = EvaluationMockProvider(case.public_input(), fixture)
    if architecture is EvaluationArchitecture.SINGLE_AGENT:
        return SingleAgentEvaluationAdapter().run(
            case,
            provider,
            maximum_context_characters=maximum_context_characters,
            maximum_output_tokens=maximum_output_tokens,
        )
    if architecture is EvaluationArchitecture.PLANNER_REVIEWER:
        return PlannerReviewerEvaluationAdapter().run(
            case,
            provider,
            maximum_context_characters=maximum_context_characters,
            maximum_output_tokens=maximum_output_tokens,
        )
    return QuantForgeTribunalEvaluationAdapter().run(
        case,
        provider,
        fixture,
        maximum_context_characters=maximum_context_characters,
        maximum_output_tokens=maximum_output_tokens,
    )


def _with_repeat_evidence(
    first: ArchitectureResult, second: ArchitectureResult
) -> ArchitectureResult:
    if first.architecture is not second.architecture or first.benchmark_id != second.benchmark_id:
        raise ValueError("repeat execution is bound to a different architecture or case")
    values = first.model_dump(mode="python", exclude={"semantic_sha256"})
    values["repeat_execution_semantic_sha256"] = second.semantic_sha256
    values["deterministic_consistent"] = first.semantic_sha256 == second.semantic_sha256
    return identified(ArchitectureResult, values)


def run_offline_evaluation(
    suite: EvaluationSuite,
    cases: tuple[BenchmarkCase, ...],
    *,
    architectures: tuple[EvaluationArchitecture, ...] = ALL_ARCHITECTURES,
    subset: Literal["full", "judge", "single_case"] = "full",
    maximum_context_characters: int = DEFAULT_MAXIMUM_CONTEXT_CHARACTERS,
    maximum_output_tokens: int = DEFAULT_MAXIMUM_OUTPUT_TOKENS,
) -> EvaluationRun:
    """Run every requested pair twice and retain code-verifiable consistency evidence."""

    if not cases or not architectures:
        raise ValueError("offline evaluation requires cases and architectures")
    if len(architectures) != len(set(architectures)):
        raise ValueError("evaluation architectures must be unique")
    catalog = load_mock_responses()
    fixture_by_id = {fixture.benchmark_id: fixture for fixture in catalog.responses}
    results: list[ArchitectureResult] = []
    for architecture in architectures:
        for case in cases:
            fixture = fixture_by_id[case.benchmark_id]
            first = _execute_once(
                architecture,
                case,
                fixture,
                maximum_context_characters=maximum_context_characters,
                maximum_output_tokens=maximum_output_tokens,
            )
            second = _execute_once(
                architecture,
                case,
                fixture,
                maximum_context_characters=maximum_context_characters,
                maximum_output_tokens=maximum_output_tokens,
            )
            results.append(_with_repeat_evidence(first, second))
    result_tuple = tuple(results)
    case_by_id = {case.benchmark_id: case for case in cases}
    scores = tuple(score_case(case_by_id[result.benchmark_id], result) for result in result_tuple)
    metrics = tuple(
        aggregate_metrics(
            architecture,
            cases,
            tuple(result for result in result_tuple if result.architecture is architecture),
            tuple(score for score in scores if score.architecture is architecture),
            {
                result.benchmark_id: bool(result.deterministic_consistent)
                for result in result_tuple
                if result.architecture is architecture
            },
        )
        for architecture in architectures
    )
    identity = {
        "mode": EvaluationMode.OFFLINE_MOCK,
        "suite_semantic_sha256": suite.semantic_sha256,
        "subset": subset,
        "architectures": architectures,
        "benchmark_ids": tuple(case.benchmark_id for case in cases),
        "provider_identity": catalog.provider_identity,
        "model_snapshot": catalog.model_snapshot,
        "maximum_context_characters": maximum_context_characters,
        "maximum_output_tokens": maximum_output_tokens,
    }
    values = {
        "schema_version": "1.0",
        "evaluation_label": EVALUATION_LABEL,
        "run_id": f"evaluation_{canonical_sha256(identity)[:24]}",
        "mode": EvaluationMode.OFFLINE_MOCK,
        "suite_id": suite.suite_id,
        "suite_version": suite.suite_version,
        "suite_semantic_sha256": suite.semantic_sha256,
        "subset": subset,
        "architectures": architectures,
        "benchmark_ids": tuple(case.benchmark_id for case in cases),
        "provider_identity": catalog.provider_identity,
        "model_snapshot": catalog.model_snapshot,
        "maximum_context_characters": maximum_context_characters,
        "maximum_output_tokens": maximum_output_tokens,
        "results": result_tuple,
        "scores": scores,
        "metrics": metrics,
        "observational_fields_excluded_from_semantic_identity": (
            "generated_at",
            "provider request and response identifiers",
            "live token usage",
            "live latency",
            "live estimated cost",
        ),
        "generated_at": _OFFLINE_GENERATED_AT,
    }
    values["semantic_sha256"] = canonical_sha256(evaluation_run_semantic_values(values))
    return EvaluationRun.model_validate(values)


__all__ = ["ALL_ARCHITECTURES", "run_offline_evaluation"]
