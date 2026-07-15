from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from quantforge.adapters.mock import MockRoleProvider, load_scenario
from quantforge.audit import AuditLog
from quantforge.domain.models import (
    ReproducibilityReview,
    ReproducibilityStatus,
    ReviewDecision,
    RoleName,
    TribunalCase,
    WorkflowState,
)
from quantforge.workflow.demo import run_demo
from quantforge.workflow.machine import StateMachine

EXPECTED = list(WorkflowState)


@pytest.mark.parametrize("scenario", ["provisional", "fragile", "inconclusive"])
def test_every_legal_workflow_transition_in_order(scenario: str) -> None:
    states = run_demo(scenario).audit_log.replay_states()
    assert list(states) == EXPECTED


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (source, target)
        for source in WorkflowState
        for target in WorkflowState
        if target.value
        != (
            EXPECTED[EXPECTED.index(source) + 1].value
            if source is not WorkflowState.CHAIR_EXPLANATION
            else ""
        )
    ],
)
def test_every_illegal_workflow_transition_is_rejected(
    simple_claim: object, source: WorkflowState, target: WorkflowState
) -> None:
    case = TribunalCase(case_id="case_illegal", state=source, claim=simple_claim)
    machine = StateMachine(case, AuditLog())
    with pytest.raises(ValueError, match="illegal workflow transition"):
        machine.advance(
            target,
            actor=RoleName.SYSTEM,
            action="illegal_transition",
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            payload={},
        )


def test_transition_prerequisites_and_skipped_approval(simple_claim: object) -> None:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    completed = run_demo("provisional").case
    assert completed.methodology_review is not None
    without_methodology = StateMachine(
        TribunalCase(
            case_id="case_no_methodology",
            state=WorkflowState.METHODOLOGY_REVIEWED,
            claim=simple_claim,
        ),
        AuditLog(),
    )
    with pytest.raises(ValueError, match="approved methodology"):
        without_methodology.advance(
            WorkflowState.HUMAN_APPROVAL,
            actor=RoleName.HUMAN_APPROVER,
            action="record_approval",
            timestamp=timestamp,
            payload={},
        )
    case = TribunalCase(
        case_id="case_prerequisite",
        state=WorkflowState.METHODOLOGY_REVIEWED,
        claim=completed.claim,
        methodology_review=completed.methodology_review,
    )
    machine = StateMachine(case, AuditLog())
    with pytest.raises(ValueError, match="explicit positive"):
        machine.advance(
            WorkflowState.HUMAN_APPROVAL,
            actor=RoleName.HUMAN_APPROVER,
            action="record_approval",
            timestamp=timestamp,
            payload={},
        )
    for source, target, required in [
        (WorkflowState.CLAIM_RECEIVED, WorkflowState.RESEARCHER_PROTOCOL_PROPOSED, "proposal"),
        (
            WorkflowState.RESEARCHER_PROTOCOL_PROPOSED,
            WorkflowState.METHODOLOGY_REVIEWED,
            "methodology_review",
        ),
        (
            WorkflowState.EXPERIMENT_EXECUTED,
            WorkflowState.STATISTICS_REVIEWED,
            "statistical_review",
        ),
        (
            WorkflowState.STATISTICS_REVIEWED,
            WorkflowState.ADVERSARIAL_REVIEWED,
            "adversarial_review",
        ),
        (
            WorkflowState.REPRODUCIBILITY_VERIFIED,
            WorkflowState.VERDICT_ELIGIBILITY_COMPUTED,
            "verdict_eligibility",
        ),
        (
            WorkflowState.VERDICT_ELIGIBILITY_COMPUTED,
            WorkflowState.CHAIR_EXPLANATION,
            "chair_explanation",
        ),
    ]:
        machine = StateMachine(
            TribunalCase(case_id="case_required", state=source, claim=simple_claim), AuditLog()
        )
        with pytest.raises(ValueError, match=required):
            machine.advance(
                target,
                actor=RoleName.SYSTEM,
                action="missing_required",
                timestamp=timestamp,
                payload={},
            )


@pytest.mark.parametrize("decision", [ReviewDecision.REJECTED, ReviewDecision.REVISION_REQUESTED])
def test_nonapproved_methodology_cannot_reach_human_approval(decision: ReviewDecision) -> None:
    result = run_demo("provisional")
    review = result.case.methodology_review
    approval = result.case.human_approval
    assert review is not None and approval is not None
    changed_review = review.model_copy(update={"decision": decision})
    case = TribunalCase(
        case_id="case_methodology_blocked",
        state=WorkflowState.METHODOLOGY_REVIEWED,
        claim=result.case.claim,
        methodology_review=changed_review,
    )
    with pytest.raises(ValueError, match="approved methodology"):
        StateMachine(case, AuditLog()).advance(
            WorkflowState.HUMAN_APPROVAL,
            actor=RoleName.HUMAN_APPROVER,
            action="record_approval",
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            payload=approval,
            updates={"human_approval": approval},
        )


def test_follow_up_skip_is_explicit_and_state_bound(simple_claim: object) -> None:
    review = ReproducibilityReview(
        review_id="review_repro",
        status=ReproducibilityStatus.VERIFIED,
        configuration_verified=True,
        manifests_verified=True,
        hashes_verified=True,
        software_identity_verified=True,
        data_lineage_verified=True,
        evidence_complete=True,
        reconstruction_status="verified",
        findings=(),
        reviewed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    wrong = StateMachine(
        TribunalCase(
            case_id="case_wrong_skip", state=WorkflowState.ADVERSARIAL_REVIEWED, claim=simple_claim
        ),
        AuditLog(),
    )
    with pytest.raises(ValueError, match="only"):
        wrong.skip_follow_up(
            actor=RoleName.SYSTEM,
            reason="explicit",
            timestamp=review.reviewed_at,
            reproducibility_review=review,
        )
    optional = StateMachine(
        TribunalCase(
            case_id="case_empty_skip", state=WorkflowState.OPTIONAL_FOLLOW_UP, claim=simple_claim
        ),
        AuditLog(),
    )
    with pytest.raises(ValueError, match="reason"):
        optional.skip_follow_up(
            actor=RoleName.SYSTEM,
            reason=" ",
            timestamp=review.reviewed_at,
            reproducibility_review=review,
        )


def test_results_before_lock_and_chair_mismatch_are_rejected(simple_claim: object) -> None:
    with pytest.raises(ValidationError, match="results cannot exist"):
        TribunalCase(
            case_id="case_early_results",
            state=WorkflowState.EXPERIMENT_EXECUTED,
            claim=simple_claim,
            evidence_ids=("evidence_early",),
        )
    result = run_demo("provisional")
    assert result.case.chair_explanation is not None
    assert result.case.verdict_eligibility is not None
    changed = result.case.chair_explanation.model_copy(update={"computed_verdict": "SUPPORTED"})
    data = result.case.model_dump(mode="python")
    data["chair_explanation"] = changed
    with pytest.raises(ValidationError, match="Chair cannot alter"):
        TribunalCase.model_validate(data)


def test_mock_provider_and_fixture_boundaries(simple_claim: object) -> None:
    with pytest.raises(ValueError, match="unknown"):
        load_scenario("real_market")
    provider = MockRoleProvider(
        load_scenario("provisional"), timestamp=datetime(2026, 1, 1, tzinfo=UTC)
    )
    assert provider.propose(simple_claim).claim_id == simple_claim.claim_id


def test_constitution_transition_rejects_missing_and_mismatched_binding() -> None:
    result = run_demo("provisional")
    approval = result.case.human_approval
    constitution = result.case.constitution
    assert approval is not None and constitution is not None
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    missing = StateMachine(
        TribunalCase(
            case_id="case_missing_constitution",
            state=WorkflowState.HUMAN_APPROVAL,
            claim=result.case.claim,
            human_approval=approval,
        ),
        AuditLog(),
    )
    with pytest.raises(ValueError, match="valid locked constitution"):
        missing.advance(
            WorkflowState.CONSTITUTION_LOCKED,
            actor=RoleName.SYSTEM,
            action="lock_constitution",
            timestamp=timestamp,
            payload={},
            updates={"constitution": "not a constitution"},
        )
    approval_data = approval.model_dump(mode="python")
    approval_data["approval_id"] = "approval_different"
    different = type(approval).model_validate(approval_data)
    mismatch = StateMachine(
        TribunalCase(
            case_id="case_mismatch_constitution",
            state=WorkflowState.HUMAN_APPROVAL,
            claim=result.case.claim,
            human_approval=different,
        ),
        AuditLog(),
    )
    with pytest.raises(ValueError, match="recorded approval"):
        mismatch.advance(
            WorkflowState.CONSTITUTION_LOCKED,
            actor=RoleName.SYSTEM,
            action="lock_constitution",
            timestamp=timestamp,
            payload=constitution,
            updates={"constitution": constitution},
        )


def test_chair_explanation_requires_eligibility(simple_claim: object) -> None:
    explanation = run_demo("provisional").case.chair_explanation
    assert explanation is not None
    with pytest.raises(ValidationError, match="requires computed"):
        TribunalCase(
            case_id="case_chair_without_policy",
            state=WorkflowState.CHAIR_EXPLANATION,
            claim=simple_claim,
            chair_explanation=explanation,
        )
