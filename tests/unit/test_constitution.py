from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from quantforge.domain.constitution import (
    create_amendment,
    create_human_approval,
    lock_constitution,
)
from quantforge.domain.models import AmendmentClassification, RoleName
from quantforge.serialization.canonical import canonical_sha256
from quantforge.workflow.demo import run_demo


def test_constitution_hash_stability_and_frozen_mutation() -> None:
    result = run_demo("provisional")
    constitution = result.case.constitution
    assert constitution is not None
    assert constitution.constitution_hash == canonical_sha256(
        constitution.model_dump(mode="python", exclude={"constitution_hash"})
    )
    with pytest.raises(ValidationError):
        constitution.constitution_hash = "0" * 64


def test_skipped_or_mismatched_approval_is_rejected() -> None:
    result = run_demo("provisional")
    proposal = result.case.proposal
    assert proposal is not None
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    rejected = create_human_approval(
        approval_id="approval_rejected",
        proposal=proposal,
        approver="test operator",
        approved_at=timestamp,
        approved=False,
    )
    with pytest.raises(ValidationError, match="explicit human approval"):
        lock_constitution(
            constitution_id="constitution_rejected",
            proposal=proposal,
            approval=rejected,
            locked_at=timestamp,
        )
    approval = create_human_approval(
        approval_id="approval_wrong",
        proposal=proposal,
        approver="test operator",
        approved_at=timestamp,
    )
    data = approval.model_dump(mode="python")
    data["proposal_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="approval does not bind"):
        lock_constitution(
            constitution_id="constitution_wrong",
            proposal=proposal,
            approval=type(approval).model_validate(data),
            locked_at=timestamp,
        )


def test_valid_amendment_is_append_only_and_primary_rewrite_is_rejected() -> None:
    result = run_demo("provisional")
    constitution = result.case.constitution
    assert constitution is not None
    timestamp = datetime(2026, 1, 2, tzinfo=UTC)
    amendment = create_amendment(
        amendment_id="amendment_admin",
        classification=AmendmentClassification.ADMINISTRATIVE,
        author_role=RoleName.RESEARCHER,
        reason="Correct a non substantive label",
        changes={"metadata.display_label": "synthetic fixture"},
        created_at=timestamp,
        parent_constitution_hash=constitution.constitution_hash,
    )
    assert amendment.parent_constitution_hash == constitution.constitution_hash
    with pytest.raises(ValidationError, match="cannot rewrite"):
        create_amendment(
            amendment_id="amendment_invalid",
            classification=AmendmentClassification.EXPLORATORY,
            author_role=RoleName.RESEARCHER,
            reason="Attempt an invalid rewrite",
            changes={"primary_hypothesis": "changed"},
            created_at=timestamp,
            parent_constitution_hash=constitution.constitution_hash,
        )


def test_tampered_constitution_and_amendment_hashes_are_rejected() -> None:
    result = run_demo("provisional")
    constitution = result.case.constitution
    assert constitution is not None
    data = constitution.model_dump(mode="python")
    data["constitution_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="hash mismatch"):
        type(constitution).model_validate(data)
    amendment = create_amendment(
        amendment_id="amendment_hash",
        classification=AmendmentClassification.REVIEWER_REQUESTED,
        author_role=RoleName.METHODOLOGY_AUDITOR,
        reason="Add a permitted robustness check",
        changes={"robustness.placebo": "required"},
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
        parent_constitution_hash=constitution.constitution_hash,
    )
    amended = amendment.model_dump(mode="python")
    amended["amendment_hash"] = "f" * 64
    with pytest.raises(ValidationError, match="hash mismatch"):
        type(amendment).model_validate(amended)


def test_constitution_rejects_experiment_mismatch() -> None:
    result = run_demo("provisional")
    proposal = result.case.proposal
    approval = result.case.human_approval
    assert proposal is not None and approval is not None
    approval_data = approval.model_dump(mode="python")
    approval_data["experiment_id"] = "experiment_other"
    wrong_approval = type(approval).model_validate(approval_data)
    with pytest.raises(ValidationError, match="experiment mismatch"):
        lock_constitution(
            constitution_id="constitution_mismatch",
            proposal=proposal,
            approval=wrong_approval,
            locked_at=datetime(2026, 1, 2, tzinfo=UTC),
        )


def test_amendment_classification_and_authority_are_enforced() -> None:
    constitution = run_demo("provisional").case.constitution
    assert constitution is not None
    with pytest.raises(ValidationError, match="classification"):
        create_amendment(
            amendment_id="amendment_wrong_class",
            classification=AmendmentClassification.EXPLORATORY,
            author_role=RoleName.RESEARCHER,
            changes={"robustness.placebo": "required"},
            created_at=datetime(2026, 1, 2, tzinfo=UTC),
            parent_constitution_hash=constitution.constitution_hash,
            reason="Add a governed follow up",
        )
    with pytest.raises(ValidationError, match="author"):
        create_amendment(
            amendment_id="amendment_wrong_author",
            classification=AmendmentClassification.REVIEWER_REQUESTED,
            author_role=RoleName.RESEARCHER,
            changes={"follow_up.placebo": "required"},
            created_at=datetime(2026, 1, 2, tzinfo=UTC),
            parent_constitution_hash=constitution.constitution_hash,
            reason="Add a governed follow up",
        )


def test_nested_primary_rewrites_and_nonmonotonic_amendments_are_rejected() -> None:
    result = run_demo("provisional")
    constitution = result.case.constitution
    assert constitution is not None
    with pytest.raises(ValidationError, match="cannot rewrite"):
        create_amendment(
            amendment_id="amendment_nested_rewrite",
            classification=AmendmentClassification.EXPLORATORY,
            author_role=RoleName.RESEARCHER,
            reason="Attempt a nested primary rewrite",
            changes={"exploratory.follow_up": {"PRIMARY_HYPOTHESIS": "changed"}},
            created_at=datetime(2026, 1, 2, tzinfo=UTC),
            parent_constitution_hash=constitution.constitution_hash,
        )
    nonmonotonic = create_amendment(
        amendment_id="amendment_nonmonotonic",
        classification=AmendmentClassification.ADMINISTRATIVE,
        author_role=RoleName.RESEARCHER,
        reason="Attempt a nonmonotonic administrative change",
        changes={"metadata.display_label": "fixture"},
        created_at=constitution.locked_at,
        parent_constitution_hash=constitution.constitution_hash,
    )
    with pytest.raises(ValidationError, match="strictly append-only"):
        result.case.model_copy(update={"amendments": (nonmonotonic,)})
