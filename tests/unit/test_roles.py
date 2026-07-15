from __future__ import annotations

import pytest

from quantforge.domain.models import RoleName
from quantforge.roles.contracts import RoleAction, RoleAuthority


@pytest.mark.parametrize(
    "role, action",
    [
        (RoleName.RESEARCHER, RoleAction.PROPOSE_PROTOCOL),
        (RoleName.METHODOLOGY_AUDITOR, RoleAction.REVIEW_METHODOLOGY),
        (RoleName.STATISTICAL_REVIEWER, RoleAction.REVIEW_STATISTICS),
        (RoleName.ADVERSARIAL_REVIEWER, RoleAction.REQUEST_CHALLENGE),
        (RoleName.REPRODUCIBILITY_REVIEWER, RoleAction.REVIEW_REPRODUCIBILITY),
        (RoleName.TRIBUNAL_CHAIR, RoleAction.EXPLAIN_VERDICT),
    ],
)
def test_role_authorized_actions(role: RoleName, action: RoleAction) -> None:
    RoleAuthority.require(role, action)


@pytest.mark.parametrize(
    "action",
    [
        RoleAction.MUTATE_LOCKED_PROTOCOL,
        RoleAction.INVENT_NUMERICAL_RESULT,
        RoleAction.EXECUTE_COMMAND,
        RoleAction.UPGRADE_VERDICT,
        RoleAction.ISSUE_TRADING_INSTRUCTION,
    ],
)
def test_role_authority_violations(action: RoleAction) -> None:
    for role in RoleName:
        with pytest.raises(PermissionError, match="not authorized"):
            RoleAuthority.require(role, action)
