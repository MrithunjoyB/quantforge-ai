from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from quantforge.adapters.mock import MockRoleProvider, load_scenario
from quantforge.domain.models import AuditEvent, ExperimentProposal, RoleName
from quantforge.roles.contracts import (
    ProviderResult,
    RoleAction,
    RoleAuthority,
    RoleProvider,
    create_provider_result,
)
from quantforge.roles.orchestrator import TribunalOrchestrator
from quantforge.serialization.canonical import canonical_sha256
from quantforge.workflow.demo import run_demo


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


def _provider() -> MockRoleProvider:
    return MockRoleProvider(
        load_scenario("provisional"),
        timestamp=datetime(2026, 1, 2, tzinfo=UTC),
    )


def test_provider_result_requires_complete_semantic_provenance() -> None:
    result = _provider().propose(run_demo("provisional").case.claim)
    value = result.model_dump(mode="json")
    semantic = value["semantic_provenance"]
    assert isinstance(semantic, dict)
    semantic.pop("model_snapshot")
    with pytest.raises(ValueError, match="model_snapshot"):
        ProviderResult[ExperimentProposal].model_validate(value)


@pytest.mark.parametrize(
    "field",
    [
        "model_snapshot",
        "prompt_template_sha256",
        "structured_output_schema_sha256",
        "validation_policy_version",
    ],
)
@pytest.mark.malicious
def test_orchestrator_rejects_mismatched_provider_semantics(field: str) -> None:
    provider = _provider()
    claim = run_demo("provisional").case.claim
    result = provider.propose(claim)
    semantic = result.semantic_provenance.model_copy(update={field: "f" * 64})
    semantic_identity = semantic.model_dump(
        mode="python", exclude={"raw_response_sha256"}, exclude_none=False
    )
    tampered = result.model_copy(
        update={
            "semantic_provenance": semantic,
            "semantic_hash": canonical_sha256(
                {"output": result.output, "provenance": semantic_identity}
            ),
        }
    )
    cast(Any, provider).propose = lambda _claim: tampered
    with pytest.raises(ValueError, match="mismatched"):
        TribunalOrchestrator(cast(RoleProvider, provider)).propose(claim)


@pytest.mark.malicious
def test_provider_cannot_advance_workflow_or_omit_result_wrapper() -> None:
    provider = _provider()
    claim = run_demo("provisional").case.claim
    cast(Any, provider).propose = lambda _claim: claim
    with pytest.raises(TypeError, match="provenance"):
        TribunalOrchestrator(cast(RoleProvider, provider)).propose(claim)

    baseline = _provider().propose(claim)
    workflow_result = create_provider_result(
        result_type=ProviderResult[AuditEvent],
        action=RoleAction.PROPOSE_PROTOCOL,
        output=run_demo("provisional").audit_log.events[-1],
        provider_identity=provider.provider_identity,
        model_snapshot=provider.model_snapshot,
        observations=baseline.observational_provenance,
    )
    cast(Any, provider).propose = lambda _claim: workflow_result
    with pytest.raises(TypeError, match="unauthorized domain output"):
        TribunalOrchestrator(cast(RoleProvider, provider)).propose(claim)


def test_observational_changes_preserve_provider_semantic_identity() -> None:
    provider = _provider()
    result = provider.propose(run_demo("provisional").case.claim)
    changed_observations = result.observational_provenance.model_copy(
        update={
            "request_id": "request_changed_only",
            "responded_at": result.observational_provenance.responded_at
            + timedelta(milliseconds=1),
            "latency_ms": 1,
            "retry_count": 1,
        }
    )
    changed = ProviderResult[ExperimentProposal].model_validate(
        result.model_copy(update={"observational_provenance": changed_observations}).model_dump()
    )
    assert changed.semantic_hash == result.semantic_hash
    assert changed.output == result.output


def test_injected_mock_providers_remain_deterministic() -> None:
    claim = run_demo("provisional").case.claim
    first = TribunalOrchestrator(_provider())
    second = TribunalOrchestrator(_provider())
    assert first.propose(claim) == second.propose(claim)
    assert first.provider_results == second.provider_results
