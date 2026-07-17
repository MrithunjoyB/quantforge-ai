from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

import quantforge.workflow as workflow_package
from quantforge.audit import AuditLog
from quantforge.domain.models import (
    FindingSeverity,
    GateStatus,
    ReproducibilityStatus,
    ResearchClaim,
    ReviewDecision,
    RoleName,
    TribunalCase,
    WorkflowState,
)
from quantforge.workflow.demo import run_demo
from quantforge.workflow.machine import StateMachine
from quantforge.workflow.rules import NEXT_STATE, RULE_BY_TARGET, RULES

EXPECTED = list(WorkflowState)


def _machine_at(state: WorkflowState, scenario: str = "provisional") -> StateMachine:
    complete = run_demo(scenario)
    count = EXPECTED.index(state) + 1
    audit = AuditLog(complete.audit_log.events[:count])
    case = audit.replay_case(require_complete=False)
    return StateMachine(case, audit)


@pytest.mark.parametrize("scenario", ["provisional", "fragile", "inconclusive"])
def test_every_legal_workflow_transition_in_order(scenario: str) -> None:
    result = run_demo(scenario)
    states = result.audit_log.replay_states()
    assert list(states) == EXPECTED
    assert result.audit_log.replay_case() == result.case


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (source, target)
        for source in WorkflowState
        for target in WorkflowState
        if target is not NEXT_STATE.get(source)
    ],
)
def test_every_illegal_workflow_transition_is_rejected(
    source: WorkflowState, target: WorkflowState
) -> None:
    machine = _machine_at(source)
    with pytest.raises(ValueError, match="illegal workflow transition"):
        machine.advance(
            target,
            actor=RoleName.SYSTEM,
            action="illegal_transition",
            timestamp=datetime(2027, 1, 1, tzinfo=UTC),
            payload={},
        )


@pytest.mark.parametrize(
    "rule",
    [
        rule
        for rule in RULES
        if rule.source is not None and rule.target is not WorkflowState.REPRODUCIBILITY_VERIFIED
    ],
)
def test_transition_actor_authority_is_enforced(rule: object) -> None:
    source = rule.source  # type: ignore[attr-defined]
    target = rule.target  # type: ignore[attr-defined]
    action = next(iter(rule.actions))  # type: ignore[attr-defined]
    machine = _machine_at(source)
    wrong_actor = (
        RoleName.TRIBUNAL_CHAIR
        if rule.actor is not RoleName.TRIBUNAL_CHAIR  # type: ignore[attr-defined]
        else RoleName.RESEARCHER
    )
    with pytest.raises(PermissionError, match="not authorized"):
        machine.advance(
            target,
            actor=wrong_actor,
            action=action,
            timestamp=datetime(2027, 1, 1, tzinfo=UTC),
            payload={},
        )


@pytest.mark.parametrize(
    ("source", "target", "required"),
    [
        (WorkflowState.CLAIM_RECEIVED, WorkflowState.RESEARCHER_PROTOCOL_PROPOSED, "proposal"),
        (
            WorkflowState.RESEARCHER_PROTOCOL_PROPOSED,
            WorkflowState.METHODOLOGY_REVIEWED,
            "methodology_review",
        ),
        (WorkflowState.METHODOLOGY_REVIEWED, WorkflowState.HUMAN_APPROVAL, "positive"),
        (WorkflowState.HUMAN_APPROVAL, WorkflowState.CONSTITUTION_LOCKED, "constitution"),
        (WorkflowState.CONSTITUTION_LOCKED, WorkflowState.EXPERIMENT_EXECUTED, "evidence"),
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
    ],
)
def test_transition_prerequisites_are_required(
    source: WorkflowState, target: WorkflowState, required: str
) -> None:
    machine = _machine_at(source)
    rule = RULE_BY_TARGET[target]
    with pytest.raises((ValidationError, ValueError), match=required):
        machine.advance(
            target,
            actor=rule.actor,
            action=next(iter(rule.actions)),
            timestamp=datetime(2027, 1, 1, tzinfo=UTC),
            payload={},
        )


@pytest.mark.parametrize("decision", [ReviewDecision.REJECTED, ReviewDecision.REVISION_REQUESTED])
def test_nonapproved_methodology_cannot_reach_human_approval(
    decision: ReviewDecision,
) -> None:
    complete = run_demo("provisional")
    review = complete.case.methodology_review
    approval = complete.case.human_approval
    assert review is not None and approval is not None
    changed_review = type(review).model_validate(
        {**review.model_dump(mode="python"), "decision": decision}
    )
    audit = AuditLog(complete.audit_log.events[:2])
    audit.append(
        timestamp=changed_review.reviewed_at,
        case_id=complete.case.case_id,
        workflow_state=WorkflowState.METHODOLOGY_REVIEWED,
        actor=RoleName.METHODOLOGY_AUDITOR,
        action="review_methodology",
        payload=changed_review,
    )
    machine = StateMachine(audit.replay_case(require_complete=False), audit)
    with pytest.raises(ValueError, match="approved methodology"):
        machine.advance(
            WorkflowState.HUMAN_APPROVAL,
            actor=RoleName.HUMAN_APPROVER,
            action="record_approval",
            timestamp=datetime(2027, 1, 1, tzinfo=UTC),
            payload=approval,
            updates={"human_approval": approval},
        )


def test_follow_up_resolution_is_explicit_state_bound_and_authorized() -> None:
    review = run_demo("provisional").case.reproducibility_review
    assert review is not None
    wrong_state = _machine_at(WorkflowState.ADVERSARIAL_REVIEWED)
    with pytest.raises(ValueError, match="only"):
        wrong_state.skip_follow_up(
            actor=RoleName.REPRODUCIBILITY_REVIEWER,
            reason="explicit",
            timestamp=datetime(2027, 1, 1, tzinfo=UTC),
            reproducibility_review=review,
        )
    optional = _machine_at(WorkflowState.OPTIONAL_FOLLOW_UP)
    with pytest.raises(ValueError, match="reason"):
        optional.skip_follow_up(
            actor=RoleName.REPRODUCIBILITY_REVIEWER,
            reason=" ",
            timestamp=datetime(2027, 1, 1, tzinfo=UTC),
            reproducibility_review=review,
        )
    with pytest.raises(PermissionError, match="not authorized"):
        optional.skip_follow_up(
            actor=RoleName.SYSTEM,
            reason="explicit",
            timestamp=datetime(2027, 1, 1, tzinfo=UTC),
            reproducibility_review=review,
        )
    with pytest.raises(ValueError, match="explicit follow-up"):
        optional.advance(
            WorkflowState.REPRODUCIBILITY_VERIFIED,
            actor=RoleName.REPRODUCIBILITY_REVIEWER,
            action="skip_follow_up",
            timestamp=datetime(2027, 1, 1, tzinfo=UTC),
            payload=review,
            updates={"reproducibility_review": review},
        )


def test_direct_state_construction_and_unaudited_restoration_are_rejected(
    simple_claim: ResearchClaim,
) -> None:
    with pytest.raises(ValidationError, match="requires proposal"):
        TribunalCase(
            case_id="case_direct_bypass",
            state=WorkflowState.CHAIR_EXPLANATION,
            claim=simple_claim,
        )
    with pytest.raises(ValueError, match="empty audit"):
        StateMachine(run_demo("provisional").case, AuditLog())


def test_constitution_transition_rejects_missing_and_mismatched_binding() -> None:
    missing = _machine_at(WorkflowState.HUMAN_APPROVAL)
    with pytest.raises(ValueError, match="valid locked constitution"):
        missing.advance(
            WorkflowState.CONSTITUTION_LOCKED,
            actor=RoleName.SYSTEM,
            action="lock_constitution",
            timestamp=datetime(2027, 1, 1, tzinfo=UTC),
            payload={},
            updates={"constitution": "not a constitution"},
        )
    mismatch = _machine_at(WorkflowState.HUMAN_APPROVAL)
    foreign = run_demo("fragile").case.constitution
    assert foreign is not None
    with pytest.raises(ValueError, match="recorded approval"):
        mismatch.advance(
            WorkflowState.CONSTITUTION_LOCKED,
            actor=RoleName.SYSTEM,
            action="lock_constitution",
            timestamp=datetime(2027, 1, 1, tzinfo=UTC),
            payload=foreign,
            updates={"constitution": foreign},
        )


def test_audit_payload_and_case_update_must_be_identical() -> None:
    machine = _machine_at(WorkflowState.CLAIM_RECEIVED)
    proposal = run_demo("provisional").case.proposal
    assert proposal is not None
    changed = type(proposal).model_validate(
        {**proposal.model_dump(mode="python"), "experiment_id": "experiment_changed"}
    )
    before = machine.audit_log.events
    with pytest.raises(ValueError, match="does not reconstruct"):
        machine.advance(
            WorkflowState.RESEARCHER_PROTOCOL_PROPOSED,
            actor=RoleName.RESEARCHER,
            action="propose_protocol",
            timestamp=datetime(2027, 1, 1, tzinfo=UTC),
            payload=proposal,
            updates={"proposal": changed},
        )
    assert machine.audit_log.events == before


def test_review_summary_cross_field_invariants_are_enforced() -> None:
    provisional = run_demo("provisional").case
    methodology = provisional.methodology_review
    adversarial = run_demo("fragile").case.adversarial_review
    reproducibility = run_demo("inconclusive").case.reproducibility_review
    assert methodology is not None and adversarial is not None and reproducibility is not None
    with pytest.raises(ValidationError, match="every governance check"):
        methodology.model_copy(update={"causality_checked": False})
    statistical = provisional.statistical_review
    assert statistical is not None
    critical = statistical.findings[0].model_copy(
        update={"severity": FindingSeverity.CRITICAL, "resolved": False}
    )
    with pytest.raises(ValidationError, match="unresolved critical"):
        methodology.model_copy(update={"findings": (critical,)})
    with pytest.raises(ValidationError, match="robustness summary"):
        adversarial.model_copy(update={"robustness_status": GateStatus.PASS})
    with pytest.raises(ValidationError, match="every reconstruction check"):
        reproducibility.model_copy(update={"status": ReproducibilityStatus.VERIFIED})


def test_workflow_public_state_machine_is_lazy_and_exact() -> None:
    assert workflow_package.StateMachine is StateMachine
    with pytest.raises(AttributeError, match="has no attribute"):
        missing = workflow_package.MissingAuthority
        del missing
