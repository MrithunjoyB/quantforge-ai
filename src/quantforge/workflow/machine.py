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

_NEXT: dict[WorkflowState, WorkflowState] = {
    WorkflowState.CLAIM_RECEIVED: WorkflowState.RESEARCHER_PROTOCOL_PROPOSED,
    WorkflowState.RESEARCHER_PROTOCOL_PROPOSED: WorkflowState.METHODOLOGY_REVIEWED,
    WorkflowState.METHODOLOGY_REVIEWED: WorkflowState.HUMAN_APPROVAL,
    WorkflowState.HUMAN_APPROVAL: WorkflowState.CONSTITUTION_LOCKED,
    WorkflowState.CONSTITUTION_LOCKED: WorkflowState.EXPERIMENT_EXECUTED,
    WorkflowState.EXPERIMENT_EXECUTED: WorkflowState.STATISTICS_REVIEWED,
    WorkflowState.STATISTICS_REVIEWED: WorkflowState.ADVERSARIAL_REVIEWED,
    WorkflowState.ADVERSARIAL_REVIEWED: WorkflowState.OPTIONAL_FOLLOW_UP,
    WorkflowState.OPTIONAL_FOLLOW_UP: WorkflowState.REPRODUCIBILITY_VERIFIED,
    WorkflowState.REPRODUCIBILITY_VERIFIED: WorkflowState.VERDICT_ELIGIBILITY_COMPUTED,
    WorkflowState.VERDICT_ELIGIBILITY_COMPUTED: WorkflowState.CHAIR_EXPLANATION,
}


class StateMachine:
    def __init__(self, case: TribunalCase, audit_log: AuditLog) -> None:
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
        expected = _NEXT.get(self.case.state)
        if target is not expected:
            raise ValueError(f"illegal workflow transition: {self.case.state} -> {target}")
        changes = dict(updates or {})
        self._validate_prerequisites(target, changes)
        changes["state"] = target
        self.case = validated_model_update(self.case, **changes)
        self.audit_log.append(
            timestamp=timestamp,
            case_id=self.case.case_id,
            workflow_state=target,
            actor=actor,
            action=action,
            payload=payload,
        )
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
        return self.advance(
            WorkflowState.REPRODUCIBILITY_VERIFIED,
            actor=actor,
            action="skip_follow_up",
            timestamp=timestamp,
            payload={"disposition": "skipped", "reason": reason},
            updates={
                "follow_up_disposition": "skipped",
                "reproducibility_review": reproducibility_review,
            },
        )

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
