from __future__ import annotations

import pytest

from quantforge.evaluation.adapters import (
    PlannerReviewerEvaluationAdapter,
    QuantForgeTribunalEvaluationAdapter,
    SingleAgentEvaluationAdapter,
)
from quantforge.evaluation.models import (
    AcceptedEvaluationResponse,
    EvaluationArchitecture,
    EvaluationRequest,
)
from quantforge.evaluation.providers import EvaluationMockProvider
from quantforge.evaluation.suite import load_mock_responses, load_suite, select_cases
from quantforge.serialization.canonical import canonical_sha256


def _case_and_provider(benchmark_id: str) -> tuple[object, EvaluationMockProvider, object]:
    suite = load_suite()
    case = select_cases(suite, benchmark_id=benchmark_id)[0]
    fixture = next(
        item for item in load_mock_responses().responses if item.benchmark_id == benchmark_id
    )
    provider = EvaluationMockProvider(case.public_input(), fixture)
    return case, provider, fixture


def test_baselines_have_exact_fair_call_structures_and_no_governance_state() -> None:
    defect, defect_provider, _ = _case_and_provider("qf-bm-001-look-ahead")
    clean, clean_provider, _ = _case_and_provider("qf-bm-024-sound-control")

    single = SingleAgentEvaluationAdapter().run(defect, defect_provider)  # type: ignore[arg-type]
    planned = PlannerReviewerEvaluationAdapter().run(defect, defect_provider)  # type: ignore[arg-type]
    clean_planned = PlannerReviewerEvaluationAdapter().run(  # type: ignore[arg-type]
        clean, clean_provider
    )

    assert single.architecture is EvaluationArchitecture.SINGLE_AGENT
    assert single.provider_call_count == 1
    assert single.independent_reviewer_count == 0
    assert planned.provider_call_count == 3
    assert planned.independent_reviewer_count == 1
    assert clean_planned.provider_call_count == 2
    for result in (single, planned, clean_planned):
        assert result.retry_count == 0
        assert result.store_transition_count == 0
        assert result.engine_invocation_count == 0
        assert not result.authority_successes
        assert not result.governed_request_semantic_hashes
        assert not result.trusted_evidence_created
        assert not result.human_approval_created_by_provider
        assert not result.constitution_mutated_by_provider
        assert not result.verdict_chosen_by_provider
    assert SingleAgentEvaluationAdapter.__slots__ == ()
    assert PlannerReviewerEvaluationAdapter.__slots__ == ()


def test_mock_provider_retains_only_public_case_material() -> None:
    _, provider, _ = _case_and_provider("qf-bm-006-multiplicity")
    assert not hasattr(provider._case, "expected_status")
    assert not hasattr(provider._case, "expected_minimum_findings")
    assert not hasattr(provider._case, "scoring_rubric")


def test_real_tribunal_adapter_uses_six_governed_calls_and_twelve_transitions() -> None:
    case, provider, fixture = _case_and_provider("qf-bm-022-provider-authority")
    result = QuantForgeTribunalEvaluationAdapter().run(  # type: ignore[arg-type]
        case, provider, fixture
    )

    assert result.architecture is EvaluationArchitecture.QUANTFORGE_TRIBUNAL
    assert result.provider_call_count == 6
    assert result.independent_reviewer_count == 4
    assert result.store_transition_count == 12
    assert result.tribunal_revision == 12
    assert result.tribunal_case_semantic_sha256 is not None
    assert len(result.governed_request_semantic_hashes) == 6
    assert len(result.governed_provider_semantic_hashes) == 6
    assert len(set(result.governed_request_semantic_hashes)) == 6
    assert result.duplicate_transition_count == 0
    assert result.authority_attempts
    assert not result.authority_successes
    assert result.engine_invocation_count == 0
    assert not result.trusted_evidence_created
    assert not result.human_approval_created_by_provider
    assert not result.verdict_upgrade_success
    assert not result.constitution_mutation_success


@pytest.mark.malicious
def test_baseline_rejects_foreign_request_and_fabricated_evidence() -> None:
    case, delegate, _ = _case_and_provider("qf-bm-003-cost-omission")

    class ForeignRequestProvider:
        provider_identity = delegate.provider_identity
        model_snapshot = delegate.model_snapshot

        def evaluate(self, request: EvaluationRequest) -> AcceptedEvaluationResponse:
            response = delegate.evaluate(request)
            foreign = "0" * 64
            return AcceptedEvaluationResponse(
                request_semantic_sha256=foreign,
                output=response.output,
                observation=response.observation,
                semantic_sha256=canonical_sha256(
                    {"request_semantic_sha256": foreign, "output": response.output}
                ),
            )

    with pytest.raises(ValueError, match="foreign request"):
        SingleAgentEvaluationAdapter().run(  # type: ignore[arg-type]
            case, ForeignRequestProvider()
        )

    class FabricatingProvider:
        provider_identity = delegate.provider_identity
        model_snapshot = delegate.model_snapshot

        def evaluate(self, request: EvaluationRequest) -> AcceptedEvaluationResponse:
            response = delegate.evaluate(request)
            finding = response.output.findings[0].model_copy(
                update={"evidence_ids": ("ev-foreign-fabricated",)}
            )
            output = response.output.model_copy(update={"findings": (finding,)})
            return AcceptedEvaluationResponse(
                request_semantic_sha256=response.request_semantic_sha256,
                output=output,
                observation=response.observation,
                semantic_sha256=canonical_sha256(
                    {
                        "request_semantic_sha256": response.request_semantic_sha256,
                        "output": output,
                    }
                ),
            )

    with pytest.raises(ValueError, match="fabricated or substituted evidence"):
        SingleAgentEvaluationAdapter().run(  # type: ignore[arg-type]
            case, FabricatingProvider()
        )
