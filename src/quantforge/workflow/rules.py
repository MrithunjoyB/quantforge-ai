"""Single source of truth for workflow order, actors, and audited actions."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from quantforge.domain.models import RoleName, WorkflowState


@dataclass(frozen=True)
class TransitionRule:
    source: WorkflowState | None
    target: WorkflowState
    actor: RoleName
    actions: frozenset[str]


RULES: tuple[TransitionRule, ...] = (
    TransitionRule(
        None,
        WorkflowState.CLAIM_RECEIVED,
        RoleName.SYSTEM,
        frozenset({"receive_claim"}),
    ),
    TransitionRule(
        WorkflowState.CLAIM_RECEIVED,
        WorkflowState.RESEARCHER_PROTOCOL_PROPOSED,
        RoleName.RESEARCHER,
        frozenset({"propose_protocol"}),
    ),
    TransitionRule(
        WorkflowState.RESEARCHER_PROTOCOL_PROPOSED,
        WorkflowState.METHODOLOGY_REVIEWED,
        RoleName.METHODOLOGY_AUDITOR,
        frozenset({"review_methodology"}),
    ),
    TransitionRule(
        WorkflowState.METHODOLOGY_REVIEWED,
        WorkflowState.HUMAN_APPROVAL,
        RoleName.HUMAN_APPROVER,
        frozenset({"record_approval"}),
    ),
    TransitionRule(
        WorkflowState.HUMAN_APPROVAL,
        WorkflowState.CONSTITUTION_LOCKED,
        RoleName.SYSTEM,
        frozenset({"lock_constitution"}),
    ),
    TransitionRule(
        WorkflowState.CONSTITUTION_LOCKED,
        WorkflowState.EXPERIMENT_EXECUTED,
        RoleName.SYSTEM,
        frozenset({"admit_engine_evidence", "load_mock_evidence"}),
    ),
    TransitionRule(
        WorkflowState.EXPERIMENT_EXECUTED,
        WorkflowState.STATISTICS_REVIEWED,
        RoleName.STATISTICAL_REVIEWER,
        frozenset({"review_statistics"}),
    ),
    TransitionRule(
        WorkflowState.STATISTICS_REVIEWED,
        WorkflowState.ADVERSARIAL_REVIEWED,
        RoleName.ADVERSARIAL_REVIEWER,
        frozenset({"review_adversarially"}),
    ),
    TransitionRule(
        WorkflowState.ADVERSARIAL_REVIEWED,
        WorkflowState.OPTIONAL_FOLLOW_UP,
        RoleName.SYSTEM,
        frozenset({"enter_follow_up"}),
    ),
    TransitionRule(
        WorkflowState.OPTIONAL_FOLLOW_UP,
        WorkflowState.REPRODUCIBILITY_VERIFIED,
        RoleName.REPRODUCIBILITY_REVIEWER,
        frozenset({"skip_follow_up", "complete_follow_up"}),
    ),
    TransitionRule(
        WorkflowState.REPRODUCIBILITY_VERIFIED,
        WorkflowState.VERDICT_ELIGIBILITY_COMPUTED,
        RoleName.SYSTEM,
        frozenset({"compute_verdict"}),
    ),
    TransitionRule(
        WorkflowState.VERDICT_ELIGIBILITY_COMPUTED,
        WorkflowState.CHAIR_EXPLANATION,
        RoleName.TRIBUNAL_CHAIR,
        frozenset({"explain_verdict"}),
    ),
)

RULE_BY_TARGET = MappingProxyType({rule.target: rule for rule in RULES})
NEXT_STATE = MappingProxyType(
    {rule.source: rule.target for rule in RULES if rule.source is not None}
)


def require_transition_authority(
    source: WorkflowState | None,
    target: WorkflowState,
    actor: RoleName,
    action: str,
) -> None:
    rule = RULE_BY_TARGET.get(target)
    if rule is None or rule.source is not source:
        raise ValueError(f"illegal workflow transition: {source} -> {target}")
    if actor is not rule.actor or action not in rule.actions:
        raise PermissionError(
            f"actor {actor.value} is not authorized for {source} -> {target} via {action}"
        )
