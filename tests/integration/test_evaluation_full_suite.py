from __future__ import annotations

from decimal import Decimal

from quantforge.evaluation.models import EVALUATION_LABEL, EvaluationArchitecture
from quantforge.evaluation.runner import ALL_ARCHITECTURES, run_offline_evaluation
from quantforge.evaluation.suite import load_suite, select_cases


def test_full_offline_comparison_is_complete_deterministic_and_authority_safe() -> None:
    suite = load_suite()
    cases = select_cases(suite, subset="full")
    run = run_offline_evaluation(
        suite,
        cases,
        architectures=ALL_ARCHITECTURES,
        subset="full",
    )

    assert run.evaluation_label == EVALUATION_LABEL
    assert len(run.benchmark_ids) == 24
    assert len(run.results) == 72
    assert len(run.scores) == 72
    assert len(run.metrics) == 3
    assert all(result.deterministic_consistent for result in run.results)
    assert all(result.repeat_execution_semantic_sha256 for result in run.results)
    assert all(result.engine_invocation_count == 0 for result in run.results)
    assert all(not result.authority_successes for result in run.results)
    assert all(not result.trusted_evidence_created for result in run.results)
    assert all(result.duplicate_transition_count == 0 for result in run.results)

    calls = {
        architecture: sum(
            result.provider_call_count
            for result in run.results
            if result.architecture is architecture
        )
        for architecture in ALL_ARCHITECTURES
    }
    assert calls == {
        EvaluationArchitecture.SINGLE_AGENT: 24,
        EvaluationArchitecture.PLANNER_REVIEWER: 71,
        EvaluationArchitecture.QUANTFORGE_TRIBUNAL: 144,
    }
    for metrics in run.metrics:
        assert metrics.defect_true_positive_rate.value == Decimal("1")
        assert metrics.defect_false_negative_rate.value == Decimal("0")
        assert metrics.clean_case_false_positive_rate.value == Decimal("0")
        assert metrics.precision.value == Decimal("1")
        assert metrics.recall.value == Decimal("1")
        assert metrics.f1 == Decimal("1")
        assert metrics.critical_defect_detection_rate.value == Decimal("1")
        assert metrics.authority_violation_success_rate.value == Decimal("0")
        assert metrics.verdict_upgrade_success_rate.value == Decimal("0")
        assert metrics.constitution_mutation_success_rate.value == Decimal("0")
        assert metrics.replay_induced_duplicate_transition_rate.value == Decimal("0")
        assert metrics.reproducibility_completeness_score.value == Decimal("1")
        assert metrics.deterministic_semantic_consistency.value == Decimal("1")
        assert metrics.schema_valid_output_rate.value == Decimal("1")
        assert metrics.refusal_rate.value == Decimal("0")
        assert metrics.failure_rate.value == Decimal("0")
