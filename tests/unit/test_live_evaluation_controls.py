from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from quantforge.evaluation.live import (
    LIVE_EVALUATION_FLAG,
    LiveCallBudget,
    authorize_live_plan,
    create_live_plan,
    load_checkpoint,
    load_verification_receipt,
    require_same_result_mode,
    save_checkpoint,
)
from quantforge.evaluation.models import (
    EvaluationArchitecture,
    EvaluationMode,
    LiveCheckpoint,
)
from quantforge.evaluation.runner import run_offline_evaluation
from quantforge.evaluation.suite import load_suite, select_cases
from quantforge.roles.contracts import RoleAction
from quantforge.serialization.safe_json import safe_write_json


def _plan(*, subset: str = "judge"):
    return create_live_plan(
        load_suite(),
        subset=subset,
        architectures=tuple(EvaluationArchitecture),
        model="approved-openai-model-snapshot",
        maximum_context_characters=24_000,
        maximum_output_tokens=2_000,
        input_price_per_million_usd=Decimal("1"),
        output_price_per_million_usd=Decimal("2"),
    )


def _receipt(path: Path, *, model: str = "approved-openai-model-snapshot") -> Path:
    governed = {
        RoleAction.PROPOSE_PROTOCOL,
        RoleAction.REVIEW_METHODOLOGY,
        RoleAction.REVIEW_STATISTICS,
        RoleAction.REQUEST_CHALLENGE,
        RoleAction.REVIEW_REPRODUCIBILITY,
        RoleAction.EXPLAIN_VERDICT,
    }
    safe_write_json(
        path,
        {
            "call_count": 6,
            "live_output_nondeterministic": True,
            "model": model,
            "provider": "openai",
            "semantic_hashes": {action.value: "0" * 64 for action in governed},
            "status": "verified",
        },
    )
    return path


def test_live_plan_has_exact_worst_case_call_and_cost_ceiling() -> None:
    judge = _plan()
    full = _plan(subset="full")
    assert judge.case_count == 7
    assert judge.maximum_call_count == 70
    assert judge.maximum_input_tokens_estimate == 96_000
    assert judge.maximum_estimated_cost_usd == Decimal("7")
    assert full.case_count == 24
    assert full.maximum_call_count == 240
    assert full.maximum_estimated_cost_usd == Decimal("24")
    assert judge.requires_official_openai
    assert judge.requires_explicit_operator_approval
    assert judge.requires_six_call_verification
    assert judge.requires_zero_provider_retries
    assert judge.provider_retry_count == 0


@pytest.mark.parametrize(
    ("subset", "architectures", "match"),
    (("single_case", tuple(EvaluationArchitecture), "subset"), ("judge", (), "nonempty")),
)
def test_live_plan_rejects_unbounded_or_ambiguous_scope(
    subset: str,
    architectures: tuple[EvaluationArchitecture, ...],
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        create_live_plan(
            load_suite(),
            subset=subset,
            architectures=architectures,
            model="model",
            maximum_context_characters=24_000,
            maximum_output_tokens=2_000,
            input_price_per_million_usd=Decimal("1"),
            output_price_per_million_usd=Decimal("1"),
        )


def test_authorization_is_fail_closed_and_binds_exact_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan()
    receipt = _receipt(tmp_path / "receipt.json")
    kwargs = {
        "approved_plan_sha256": plan.plan_sha256,
        "approved_call_budget": plan.maximum_call_count,
        "approved_cost_cap_usd": plan.maximum_estimated_cost_usd,
        "verification_receipt": receipt,
    }
    monkeypatch.delenv(LIVE_EVALUATION_FLAG, raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(PermissionError, match=LIVE_EVALUATION_FLAG):
        authorize_live_plan(plan, **kwargs)

    monkeypatch.setenv(LIVE_EVALUATION_FLAG, "1")
    with pytest.raises(PermissionError, match="plan"):
        authorize_live_plan(plan, **{**kwargs, "approved_plan_sha256": "f" * 64})
    with pytest.raises(PermissionError, match="call budget"):
        authorize_live_plan(
            plan,
            **{**kwargs, "approved_call_budget": plan.maximum_call_count - 1},
        )
    with pytest.raises(PermissionError, match="cost cap"):
        authorize_live_plan(
            plan,
            **{
                **kwargs,
                "approved_cost_cap_usd": plan.maximum_estimated_cost_usd - Decimal("0.01"),
            },
        )
    with pytest.raises(PermissionError, match="credentials"):
        authorize_live_plan(plan, **kwargs)

    monkeypatch.setenv("OPENAI_API_KEY", "test-only-not-a-real-key")
    accepted = authorize_live_plan(plan, **kwargs)
    assert accepted.call_count == 6
    assert accepted.model == plan.model
    with pytest.raises(ValueError, match="model differs"):
        load_verification_receipt(
            _receipt(tmp_path / "wrong-model.json", model="other-model"),
            expected_model=plan.model,
        )


def test_live_call_budget_fails_before_partial_case_or_extra_call() -> None:
    budget = LiveCallBudget(approved_calls=6)
    budget.reserve_case(6)
    for expected_remaining in range(5, -1, -1):
        budget.consume()
        assert budget.remaining_calls == expected_remaining
    with pytest.raises(PermissionError, match="exhausted"):
        budget.consume()
    with pytest.raises(PermissionError, match="complete case"):
        budget.reserve_case(1)
    with pytest.raises(ValueError, match="invalid"):
        LiveCallBudget(0)
    with pytest.raises(ValueError, match="invalid"):
        LiveCallBudget(2, consumed_calls=3)


def test_live_checkpoints_are_namespaced_plan_bound_and_duplicate_free(
    tmp_path: Path,
) -> None:
    plan = _plan()
    path = tmp_path / "checkpoint.json"
    empty = load_checkpoint(path, plan)
    assert empty.namespace == "live_openai"
    assert empty.calls_consumed == 0

    suite = load_suite()
    case = select_cases(suite, benchmark_id="qf-bm-024-sound-control")
    run = run_offline_evaluation(
        suite,
        case,
        architectures=(EvaluationArchitecture.SINGLE_AGENT,),
        subset="single_case",
    )
    checkpoint = LiveCheckpoint(
        namespace="live_openai",
        plan_sha256=plan.plan_sha256,
        completed_results=run.results,
        calls_consumed=1,
        updated_at=empty.updated_at,
    )
    save_checkpoint(path, checkpoint)
    assert load_checkpoint(path, plan) == checkpoint

    duplicate = checkpoint.model_copy(
        update={"completed_results": (run.results[0], run.results[0])}
    )
    save_checkpoint(path, duplicate)
    with pytest.raises(ValueError, match="duplicate"):
        load_checkpoint(path, plan)

    save_checkpoint(path, checkpoint)
    other = create_live_plan(
        suite,
        subset="judge",
        architectures=(EvaluationArchitecture.SINGLE_AGENT,),
        model=plan.model,
        maximum_context_characters=24_000,
        maximum_output_tokens=2_000,
        input_price_per_million_usd=Decimal("1"),
        output_price_per_million_usd=Decimal("2"),
    )
    with pytest.raises(ValueError, match="different approved plan"):
        load_checkpoint(path, other)


def test_mock_and_live_quality_populations_cannot_be_compared_as_equivalent() -> None:
    require_same_result_mode(EvaluationMode.OFFLINE_MOCK, EvaluationMode.OFFLINE_MOCK)
    with pytest.raises(ValueError, match="cannot be compared"):
        require_same_result_mode(EvaluationMode.OFFLINE_MOCK, EvaluationMode.LIVE_OPENAI)
