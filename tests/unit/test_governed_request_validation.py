from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from quantforge.evidence.bundle import amendment_chain_hash
from quantforge.roles.contracts import RoleAction
from quantforge.roles.requests import EvidenceSummary, GovernedRoleRequest, RoleRequestBuilder
from quantforge.workflow.demo import run_demo

_AT = datetime(2026, 5, 1, tzinfo=UTC)


def _statistical_request() -> GovernedRoleRequest:
    demo = run_demo("provisional")
    case = demo.audit_log.replay_cases(require_complete=False)[5]
    assert case.constitution is not None
    evidence = demo.evidence_ledger.snapshot().evidence[0]
    summary = EvidenceSummary(
        case_id=case.case_id,
        case_revision=6,
        constitution_identity=case.constitution.constitution_hash,
        amendment_chain_identity=amendment_chain_hash(case.amendments),
        evidence_id=evidence.evidence_id,
        numeric_fact_ids=tuple(fact.fact_id for fact in evidence.numeric_facts),
        summary="Bounded synthetic evidence summary",
    )
    return RoleRequestBuilder().build(
        action=RoleAction.REVIEW_STATISTICS,
        case=case,
        case_revision=6,
        effective_at=_AT,
        evidence_summaries=(summary,),
    )


@pytest.mark.malicious
@pytest.mark.parametrize(
    "field,value,message",
    [
        ("prompt_template_sha256", "f" * 64, "prompt hash"),
        ("evidence_references", ("evidence_provisional_01",) * 2, "evidence references"),
        ("numeric_fact_references", ("fact_provisional_01",) * 2, "numeric-fact"),
        ("maximum_context_characters", 1, "character budget"),
        ("approximate_input_token_budget", 1, "token budget"),
        ("context_identity", "e" * 64, "context identity"),
        ("request_semantic_sha256", "d" * 64, "semantic identity"),
    ],
)
def test_request_identity_and_budget_mutations_fail_closed(
    field: str,
    value: object,
    message: str,
) -> None:
    data = _statistical_request().model_dump(mode="python")
    data[field] = value
    with pytest.raises(ValidationError, match=message):
        GovernedRoleRequest.model_validate(data)


@pytest.mark.malicious
def test_context_order_and_unknown_fields_fail_closed() -> None:
    request = _statistical_request()
    data = request.model_dump(mode="python")
    data["context"] = tuple(reversed(request.context))
    with pytest.raises(ValidationError, match="deterministic ordering"):
        GovernedRoleRequest.model_validate(data)
    data = request.model_dump(mode="python")
    data["unknown_remote_context"] = "hidden case"
    with pytest.raises(ValidationError, match="Extra inputs"):
        GovernedRoleRequest.model_validate(data)


@pytest.mark.malicious
@pytest.mark.parametrize("summary", ["e\u0301", "hidden\u200btext", "hidden\x00text"])
def test_context_rejects_noncanonical_and_invisible_unicode(summary: str) -> None:
    base = _statistical_request()
    first = next(item for item in base.context if item.kind.value == "untrusted_evidence_summary")
    evidence = EvidenceSummary.model_validate_json(first.content, strict=True)
    with pytest.raises(ValidationError, match=r"NFC|Unicode|code point"):
        evidence.model_copy(update={"summary": summary})


@pytest.mark.malicious
def test_builder_rejects_wrong_state_missing_duplicate_and_unknown_evidence() -> None:
    demo = run_demo("provisional")
    cases = demo.audit_log.replay_cases(require_complete=False)
    with pytest.raises(ValueError, match="not eligible"):
        RoleRequestBuilder().build(
            action=RoleAction.PROPOSE_PROTOCOL,
            case=cases[1],
            case_revision=2,
            effective_at=_AT,
        )
    executed = cases[5]
    with pytest.raises(ValueError, match="requires supplied evidence"):
        RoleRequestBuilder().build(
            action=RoleAction.REVIEW_STATISTICS,
            case=executed,
            case_revision=6,
            effective_at=_AT,
        )
    request = _statistical_request()
    item = next(item for item in request.context if item.kind.value == "untrusted_evidence_summary")
    summary = EvidenceSummary.model_validate_json(item.content, strict=True)
    with pytest.raises(ValueError, match="unique evidence"):
        RoleRequestBuilder().build(
            action=RoleAction.REVIEW_STATISTICS,
            case=executed,
            case_revision=6,
            effective_at=_AT,
            evidence_summaries=(summary, summary),
        )
    unknown = summary.model_copy(update={"evidence_id": "evidence_unknown"})
    with pytest.raises(ValueError, match="not admitted"):
        RoleRequestBuilder().build(
            action=RoleAction.REVIEW_STATISTICS,
            case=executed,
            case_revision=6,
            effective_at=_AT,
            evidence_summaries=(unknown,),
        )


@pytest.mark.malicious
def test_evidence_summary_rejects_duplicate_numeric_fact_identifiers() -> None:
    request = _statistical_request()
    item = next(item for item in request.context if item.kind.value == "untrusted_evidence_summary")
    summary = EvidenceSummary.model_validate_json(item.content, strict=True)
    fact_id = summary.numeric_fact_ids[0]
    with pytest.raises(ValidationError, match="unique"):
        summary.model_copy(update={"numeric_fact_ids": (fact_id, fact_id)})


def test_chair_receives_every_validated_review_as_bounded_untrusted_context() -> None:
    demo = run_demo("provisional")
    case = demo.audit_log.replay_cases(require_complete=False)[10]
    assert case.constitution is not None
    evidence = demo.evidence_ledger.snapshot().evidence[0]
    request = RoleRequestBuilder().build(
        action=RoleAction.EXPLAIN_VERDICT,
        case=case,
        case_revision=11,
        effective_at=_AT,
        evidence_summaries=(
            EvidenceSummary(
                case_id=case.case_id,
                case_revision=11,
                constitution_identity=case.constitution.constitution_hash,
                amendment_chain_identity=amendment_chain_hash(case.amendments),
                evidence_id=evidence.evidence_id,
                numeric_fact_ids=tuple(fact.fact_id for fact in evidence.numeric_facts),
                summary="Bounded synthetic evidence summary",
            ),
        ),
    )
    prior_context = "\n".join(
        item.content for item in request.context if item.kind.value == "untrusted_prior_role_output"
    )
    assert case.methodology_review is not None
    assert case.statistical_review is not None
    assert case.adversarial_review is not None
    assert case.reproducibility_review is not None
    for review_id in (
        case.methodology_review.review_id,
        case.statistical_review.review_id,
        case.adversarial_review.review_id,
        case.reproducibility_review.review_id,
    ):
        assert review_id in prior_context
