"""Fail-closed live-evaluation planning, authorization, cost, and resume controls."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from quantforge.evaluation.models import (
    EvaluationArchitecture,
    EvaluationMode,
    EvaluationSuite,
    LiveCheckpoint,
    LiveEvaluationPlan,
    LiveVerificationReceipt,
)
from quantforge.serialization.canonical import canonical_json, canonical_sha256
from quantforge.serialization.safe_json import safe_load_json, safe_write_json

LIVE_EVALUATION_FLAG = "QUANTFORGE_LIVE_EVALUATION"
_MAXIMUM_CALLS_PER_CASE = {
    EvaluationArchitecture.SINGLE_AGENT: 1,
    EvaluationArchitecture.PLANNER_REVIEWER: 3,
    EvaluationArchitecture.QUANTFORGE_TRIBUNAL: 6,
}


def create_live_plan(
    suite: EvaluationSuite,
    *,
    subset: str,
    architectures: tuple[EvaluationArchitecture, ...],
    model: str,
    maximum_context_characters: int,
    maximum_output_tokens: int,
    input_price_per_million_usd: Decimal,
    output_price_per_million_usd: Decimal,
) -> LiveEvaluationPlan:
    if subset not in {"full", "judge"}:
        raise ValueError("live evaluation subset must be full or judge")
    if not architectures or len(architectures) != len(set(architectures)):
        raise ValueError("live evaluation architectures must be nonempty and unique")
    case_count = len(suite.cases) if subset == "full" else len(suite.judge_subset)
    calls_per_case = sum(_MAXIMUM_CALLS_PER_CASE[item] for item in architectures)
    maximum_call_count = case_count * calls_per_case
    maximum_input_tokens = maximum_context_characters * 4
    per_call_cost = (
        Decimal(maximum_input_tokens) * input_price_per_million_usd
        + Decimal(maximum_output_tokens) * output_price_per_million_usd
    ) / Decimal(1_000_000)
    values = {
        "schema_version": "1.0",
        "suite_semantic_sha256": suite.semantic_sha256,
        "subset": subset,
        "case_count": case_count,
        "architectures": architectures,
        "architecture_count": len(architectures),
        "maximum_call_count": maximum_call_count,
        "model": model.strip(),
        "maximum_context_characters": maximum_context_characters,
        "maximum_input_tokens_estimate": maximum_input_tokens,
        "maximum_output_tokens": maximum_output_tokens,
        "provider_retry_count": 0,
        "input_price_per_million_usd": input_price_per_million_usd,
        "output_price_per_million_usd": output_price_per_million_usd,
        "maximum_estimated_cost_usd": per_call_cost * Decimal(maximum_call_count),
        "requires_official_openai": True,
        "requires_explicit_operator_approval": True,
        "requires_six_call_verification": True,
        "requires_zero_provider_retries": True,
    }
    values["plan_sha256"] = canonical_sha256(values)
    return LiveEvaluationPlan.model_validate(values)


def load_verification_receipt(path: Path, *, expected_model: str) -> LiveVerificationReceipt:
    receipt = LiveVerificationReceipt.model_validate_json(canonical_json(safe_load_json(path)))
    if receipt.model != expected_model:
        raise ValueError("six-call verification model differs from the live evaluation model")
    return receipt


def authorize_live_plan(
    plan: LiveEvaluationPlan,
    *,
    approved_plan_sha256: str,
    approved_call_budget: int,
    approved_cost_cap_usd: Decimal,
    verification_receipt: Path,
) -> LiveVerificationReceipt:
    """Authorize only an exact plan; this function performs no provider call."""

    if os.environ.get(LIVE_EVALUATION_FLAG) != "1":
        raise PermissionError(f"set {LIVE_EVALUATION_FLAG}=1 for explicit live authorization")
    if approved_plan_sha256 != plan.plan_sha256:
        raise PermissionError("operator approval does not match the exact live plan")
    if approved_call_budget < plan.maximum_call_count:
        raise PermissionError("approved call budget is below the plan maximum")
    if approved_cost_cap_usd < plan.maximum_estimated_cost_usd:
        raise PermissionError("approved cost cap is below the plan maximum estimate")
    if not os.environ.get("OPENAI_API_KEY"):
        raise PermissionError("official OpenAI credentials are unavailable from the environment")
    return load_verification_receipt(verification_receipt, expected_model=plan.model)


class LiveCallBudget:
    """In-memory hard ceiling used by a later authorized provider execution loop."""

    def __init__(self, approved_calls: int, *, consumed_calls: int = 0) -> None:
        if approved_calls < 1 or consumed_calls < 0 or consumed_calls > approved_calls:
            raise ValueError("live call budget is invalid")
        self._approved_calls = approved_calls
        self._consumed_calls = consumed_calls

    @property
    def consumed_calls(self) -> int:
        return self._consumed_calls

    @property
    def remaining_calls(self) -> int:
        return self._approved_calls - self._consumed_calls

    def consume(self) -> None:
        if self.remaining_calls < 1:
            raise PermissionError("approved live call budget is exhausted")
        self._consumed_calls += 1

    def reserve_case(self, maximum_case_calls: int) -> None:
        if maximum_case_calls < 1 or maximum_case_calls > self.remaining_calls:
            raise PermissionError("remaining live budget cannot cover the next complete case")


def load_checkpoint(path: Path, plan: LiveEvaluationPlan) -> LiveCheckpoint:
    if not path.exists():
        return LiveCheckpoint(
            namespace="live_openai",
            plan_sha256=plan.plan_sha256,
            completed_results=(),
            calls_consumed=0,
            updated_at=datetime.now(UTC),
        )
    checkpoint = LiveCheckpoint.model_validate_json(canonical_json(safe_load_json(path)))
    if checkpoint.plan_sha256 != plan.plan_sha256:
        raise ValueError("live checkpoint belongs to a different approved plan")
    pairs = {(result.architecture, result.benchmark_id) for result in checkpoint.completed_results}
    if len(pairs) != len(checkpoint.completed_results):
        raise ValueError("live checkpoint contains duplicate completed cases")
    return checkpoint


def save_checkpoint(path: Path, checkpoint: LiveCheckpoint) -> None:
    safe_write_json(path, checkpoint)


def require_same_result_mode(left: EvaluationMode, right: EvaluationMode) -> None:
    if left is not right:
        raise ValueError(
            "mock and live quality metrics cannot be compared as equivalent result populations"
        )


__all__ = [
    "LIVE_EVALUATION_FLAG",
    "LiveCallBudget",
    "authorize_live_plan",
    "create_live_plan",
    "load_checkpoint",
    "load_verification_receipt",
    "require_same_result_mode",
    "save_checkpoint",
]
