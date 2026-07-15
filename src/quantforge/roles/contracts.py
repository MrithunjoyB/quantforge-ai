"""Provider-neutral role contracts; all outputs must already be validated domain models."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from quantforge.domain.models import (
    AdversarialReview,
    ChairExplanation,
    ExperimentProposal,
    MethodologyReview,
    ReproducibilityReview,
    ResearchClaim,
    RoleName,
    StatisticalReview,
    TribunalCase,
    VerdictEligibility,
)


class RoleAction(StrEnum):
    PROPOSE_PROTOCOL = "propose_protocol"
    REVIEW_METHODOLOGY = "review_methodology"
    REVIEW_STATISTICS = "review_statistics"
    REQUEST_CHALLENGE = "request_challenge"
    REVIEW_REPRODUCIBILITY = "review_reproducibility"
    EXPLAIN_VERDICT = "explain_verdict"
    MUTATE_LOCKED_PROTOCOL = "mutate_locked_protocol"
    INVENT_NUMERICAL_RESULT = "invent_numerical_result"
    EXECUTE_COMMAND = "execute_command"
    UPGRADE_VERDICT = "upgrade_verdict"
    ISSUE_TRADING_INSTRUCTION = "issue_trading_instruction"


_ALLOWED: dict[RoleName, frozenset[RoleAction]] = {
    RoleName.RESEARCHER: frozenset({RoleAction.PROPOSE_PROTOCOL}),
    RoleName.METHODOLOGY_AUDITOR: frozenset({RoleAction.REVIEW_METHODOLOGY}),
    RoleName.STATISTICAL_REVIEWER: frozenset({RoleAction.REVIEW_STATISTICS}),
    RoleName.ADVERSARIAL_REVIEWER: frozenset({RoleAction.REQUEST_CHALLENGE}),
    RoleName.REPRODUCIBILITY_REVIEWER: frozenset({RoleAction.REVIEW_REPRODUCIBILITY}),
    RoleName.TRIBUNAL_CHAIR: frozenset({RoleAction.EXPLAIN_VERDICT}),
}


class RoleAuthority:
    @staticmethod
    def require(role: RoleName, action: RoleAction) -> None:
        if action not in _ALLOWED.get(role, frozenset()):
            raise PermissionError(f"role {role.value} is not authorized for {action.value}")


class RoleProvider(Protocol):
    """Future providers must validate external output before returning these contracts."""

    def propose(self, claim: ResearchClaim) -> ExperimentProposal: ...

    def review_methodology(self, proposal: ExperimentProposal) -> MethodologyReview: ...

    def review_statistics(self, case: TribunalCase) -> StatisticalReview: ...

    def review_adversarially(self, case: TribunalCase) -> AdversarialReview: ...

    def review_reproducibility(self, case: TribunalCase) -> ReproducibilityReview: ...

    def explain(self, case: TribunalCase, eligibility: VerdictEligibility) -> ChairExplanation: ...
