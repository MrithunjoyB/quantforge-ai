#!/usr/bin/env python3
"""Explicit six-call official OpenAI structured-provider verification."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta

from quantforge.domain.models import TribunalCase, Verdict
from quantforge.evidence.bundle import amendment_chain_hash
from quantforge.providers.config import OpenAIProviderConfig, ProviderMode
from quantforge.providers.failures import ProviderFailure
from quantforge.providers.openai import OpenAIStructuredRoleProvider
from quantforge.roles.contracts import ProviderResultAny, RoleAction
from quantforge.roles.governance import role_contract
from quantforge.roles.requests import EvidenceSummary, RoleRequestBuilder
from quantforge.roles.validation import validate_role_output
from quantforge.serialization.canonical import canonical_json
from quantforge.workflow.demo import run_demo

LIVE_FLAG = "QUANTFORGE_LIVE_OPENAI"
MODEL_VARIABLE = "OPENAI_MODEL"
MAXIMUM_CALL_COUNT = 6

_ROLE_CASE_INDEX = (
    (RoleAction.PROPOSE_PROTOCOL, 0),
    (RoleAction.REVIEW_METHODOLOGY, 1),
    (RoleAction.REVIEW_STATISTICS, 5),
    (RoleAction.REQUEST_CHALLENGE, 6),
    (RoleAction.REVIEW_REPRODUCIBILITY, 8),
    (RoleAction.EXPLAIN_VERDICT, 10),
)


def _summary(case: TribunalCase, revision: int) -> tuple[EvidenceSummary, ...]:
    if not case.evidence_ids:
        return ()
    if case.constitution is None:
        raise RuntimeError("synthetic live case lacks its code-owned constitution")
    evidence = run_demo("provisional").evidence_ledger.snapshot().evidence[0]
    return (
        EvidenceSummary(
            case_id=case.case_id,
            case_revision=revision,
            constitution_identity=case.constitution.constitution_hash,
            amendment_chain_identity=amendment_chain_hash(case.amendments),
            evidence_id=evidence.evidence_id,
            numeric_fact_ids=tuple(fact.fact_id for fact in evidence.numeric_facts),
            summary="Bounded non-sensitive synthetic evidence supplied by QuantForge code",
        ),
    )


def _verify_chair_is_explanatory_only(
    result: ProviderResultAny,
    request: object,
    case: TribunalCase,
) -> None:
    from quantforge.domain.models import ChairExplanation
    from quantforge.roles.requests import GovernedRoleRequest

    if not isinstance(request, GovernedRoleRequest) or not isinstance(
        result.output, ChairExplanation
    ):
        raise RuntimeError("live Chair verification received the wrong governed types")
    changed = (
        Verdict.SUPPORTED
        if result.output.computed_verdict is not Verdict.SUPPORTED
        else Verdict.REJECTED
    )
    attempted_upgrade = result.output.model_copy(update={"computed_verdict": changed})
    try:
        validate_role_output(request, attempted_upgrade, case=case)
    except PermissionError:
        return
    raise RuntimeError("Chair authority test failed: a verdict change was accepted")


def main() -> int:
    print(f"Estimated and enforced maximum official OpenAI call count: {MAXIMUM_CALL_COUNT}")
    print(
        "Live model output is nondeterministic; summary field order and hashing are deterministic."
    )
    if os.environ.get(LIVE_FLAG) != "1":
        print(f"BLOCKED: set {LIVE_FLAG}=1 to authorize the bounded live verification.")
        return 2
    model = os.environ.get(MODEL_VARIABLE)
    if model is None or not model.strip():
        print(f"BLOCKED: set {MODEL_VARIABLE} to an operator-selected official model identifier.")
        return 2
    if not os.environ.get("OPENAI_API_KEY"):
        print("BLOCKED: OPENAI_API_KEY is required through the environment.")
        return 2

    provider = OpenAIStructuredRoleProvider(
        OpenAIProviderConfig(
            mode=ProviderMode.OPENAI,
            model=model,
            maximum_retries=0,
            timeout_seconds=30,
        )
    )
    demo = run_demo("provisional")
    cases = demo.audit_log.replay_cases(require_complete=False)
    builder = RoleRequestBuilder()
    started = datetime(2026, 4, 1, tzinfo=UTC)
    semantic_hashes: dict[str, str] = {}

    try:
        for offset, (action, case_index) in enumerate(_ROLE_CASE_INDEX):
            case = cases[case_index]
            revision = case_index + 1
            request = builder.build(
                action=action,
                case=case,
                case_revision=revision,
                effective_at=started + timedelta(minutes=offset),
                evidence_summaries=_summary(case, revision),
                code_owned_reproducibility_verified=(action is RoleAction.REVIEW_REPRODUCIBILITY),
            )
            result = provider.invoke(request)
            validate_role_output(request, result.output, case=case)
            semantic = result.semantic_provenance
            contract = role_contract(action)
            if (
                semantic.role is not contract.role
                or semantic.canonical_request_sha256 != request.request_semantic_sha256
                or semantic.provider_identity != "openai"
                or semantic.requested_model != model
                or semantic.context_item_identities
                != tuple(item.identity for item in request.context)
            ):
                raise RuntimeError("live structured call returned mismatched provenance")
            semantic_hashes[action.value] = result.semantic_hash
            if action is RoleAction.EXPLAIN_VERDICT:
                _verify_chair_is_explanatory_only(result, request, case)
    except ProviderFailure as error:
        print(f"FAILED: {error}")
        return 1
    except Exception as error:
        print(f"FAILED: {type(error).__name__}; sensitive details suppressed")
        return 1

    print(
        canonical_json(
            {
                "call_count": MAXIMUM_CALL_COUNT,
                "live_output_nondeterministic": True,
                "model": model,
                "provider": "openai",
                "semantic_hashes": semantic_hashes,
                "status": "verified",
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
