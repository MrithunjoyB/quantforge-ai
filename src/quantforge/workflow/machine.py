"""Locked deterministic workflow with validated prerequisites and explicit follow-up skip."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from quantforge.audit import AuditLog
from quantforge.domain.models import (
    ExperimentConstitution,
    HumanApproval,
    ReproducibilityReview,
    ReviewDecision,
    RoleName,
    TribunalCase,
    WorkflowState,
    validated_model_update,
)
from quantforge.workflow.rules import NEXT_STATE, require_transition_authority


class StateMachine:
    def __init__(self, case: TribunalCase, audit_log: AuditLog) -> None:
        restored = audit_log.replay_case(require_complete=False)
        if restored != case:
            raise ValueError("state machine case does not match its complete audited history")
        self.case = case
        self.audit_log = audit_log

    def advance(
        self,
        target: WorkflowState,
        *,
        actor: RoleName,
        action: str,
        timestamp: datetime,
        payload: Any,
        updates: dict[str, Any] | None = None,
    ) -> TribunalCase:
        expected = NEXT_STATE.get(self.case.state)
        if target is not expected:
            raise ValueError(f"illegal workflow transition: {self.case.state} -> {target}")
        if target is WorkflowState.REPRODUCIBILITY_VERIFIED:
            raise ValueError("use an explicit follow-up completion or skip operation")
        require_transition_authority(self.case.state, target, actor, action)
        changes = dict(updates or {})
        self._validate_prerequisites(target, changes)
        changes["state"] = target
        new_case = validated_model_update(self.case, **changes)
        self.audit_log.append(
            timestamp=timestamp,
            case_id=self.case.case_id,
            workflow_state=target,
            actor=actor,
            action=action,
            payload=payload,
            expected_case=new_case,
        )
        self.case = new_case
        return self.case

    def skip_follow_up(
        self,
        *,
        actor: RoleName,
        reason: str,
        timestamp: datetime,
        reproducibility_review: ReproducibilityReview,
    ) -> TribunalCase:
        if self.case.state is not WorkflowState.OPTIONAL_FOLLOW_UP:
            raise ValueError("follow-up can be skipped only from OPTIONAL_FOLLOW_UP")
        if not reason.strip():
            raise ValueError("follow-up skip requires an explicit reason")
        return self._record_follow_up(
            disposition="skipped",
            actor=actor,
            reason=reason,
            timestamp=timestamp,
            reproducibility_review=reproducibility_review,
        )

    def complete_follow_up(
        self,
        *,
        actor: RoleName,
        reason: str,
        timestamp: datetime,
        reproducibility_review: ReproducibilityReview,
    ) -> TribunalCase:
        return self._record_follow_up(
            disposition="completed",
            actor=actor,
            reason=reason,
            timestamp=timestamp,
            reproducibility_review=reproducibility_review,
        )

    def _record_follow_up(
        self,
        *,
        disposition: str,
        actor: RoleName,
        reason: str,
        timestamp: datetime,
        reproducibility_review: ReproducibilityReview,
    ) -> TribunalCase:
        if self.case.state is not WorkflowState.OPTIONAL_FOLLOW_UP:
            raise ValueError("follow-up can be resolved only from OPTIONAL_FOLLOW_UP")
        if not reason.strip():
            raise ValueError("follow-up disposition requires an explicit reason")
        action = "skip_follow_up" if disposition == "skipped" else "complete_follow_up"
        require_transition_authority(
            self.case.state,
            WorkflowState.REPRODUCIBILITY_VERIFIED,
            actor,
            action,
        )
        new_case = validated_model_update(
            self.case,
            state=WorkflowState.REPRODUCIBILITY_VERIFIED,
            follow_up_disposition=disposition,
            reproducibility_review=reproducibility_review,
        )
        payload = {
            "disposition": disposition,
            "reason": reason,
            "reproducibility_review": reproducibility_review,
        }
        self.audit_log.append(
            timestamp=timestamp,
            case_id=self.case.case_id,
            workflow_state=WorkflowState.REPRODUCIBILITY_VERIFIED,
            actor=actor,
            action=action,
            payload=payload,
            expected_case=new_case,
        )
        self.case = new_case
        return self.case

    def _validate_prerequisites(self, target: WorkflowState, updates: dict[str, Any]) -> None:
        if target is WorkflowState.HUMAN_APPROVAL:
            methodology = self.case.methodology_review
            if methodology is None or methodology.decision is not ReviewDecision.APPROVED:
                raise ValueError("human approval requires an approved methodology review")
            approval = updates.get("human_approval")
            if not isinstance(approval, HumanApproval) or not approval.approved:
                raise ValueError("explicit positive human approval is required")
        if target is WorkflowState.CONSTITUTION_LOCKED:
            constitution = updates.get("constitution")
            if not isinstance(constitution, ExperimentConstitution):
                raise ValueError("a valid locked constitution is required")
            if (
                not self.case.human_approval
                or constitution.human_approval != self.case.human_approval
            ):
                raise ValueError("constitution must use the recorded approval")
        required_fields = {
            WorkflowState.RESEARCHER_PROTOCOL_PROPOSED: "proposal",
            WorkflowState.METHODOLOGY_REVIEWED: "methodology_review",
            WorkflowState.STATISTICS_REVIEWED: "statistical_review",
            WorkflowState.ADVERSARIAL_REVIEWED: "adversarial_review",
            WorkflowState.REPRODUCIBILITY_VERIFIED: "reproducibility_review",
            WorkflowState.VERDICT_ELIGIBILITY_COMPUTED: "verdict_eligibility",
            WorkflowState.CHAIR_EXPLANATION: "chair_explanation",
        }
        field = required_fields.get(target)
        if field and updates.get(field) is None:
            raise ValueError(f"transition requires {field}")
