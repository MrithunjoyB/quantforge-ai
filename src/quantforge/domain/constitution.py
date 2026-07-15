"""Factories for locked experiment constitutions and append-only amendments."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from quantforge.domain.models import (
    AmendmentClassification,
    ConstitutionAmendment,
    ExperimentConstitution,
    ExperimentProposal,
    HumanApproval,
    JsonValue,
    RoleName,
)
from quantforge.serialization.canonical import canonical_sha256


def create_human_approval(
    *,
    approval_id: str,
    proposal: ExperimentProposal,
    approver: str,
    approved_at: datetime,
    approved: bool = True,
) -> HumanApproval:
    return HumanApproval(
        approval_id=approval_id,
        experiment_id=proposal.experiment_id,
        approved=approved,
        approver=approver,
        approved_at=approved_at,
        proposal_hash=canonical_sha256(proposal),
    )


def lock_constitution(
    *,
    constitution_id: str,
    proposal: ExperimentProposal,
    approval: HumanApproval,
    locked_at: datetime,
) -> ExperimentConstitution:
    payload: dict[str, Any] = {
        "constitution_id": constitution_id,
        "schema_version": "1.0",
        "experiment_id": proposal.experiment_id,
        "proposal": proposal,
        "human_approval": approval,
        "locked_at": locked_at,
    }
    return ExperimentConstitution(**payload, constitution_hash=canonical_sha256(payload))


def create_amendment(
    *,
    amendment_id: str,
    classification: AmendmentClassification,
    author_role: RoleName,
    reason: str,
    changes: dict[str, JsonValue],
    created_at: datetime,
    parent_constitution_hash: str,
) -> ConstitutionAmendment:
    payload: dict[str, Any] = {
        "amendment_id": amendment_id,
        "schema_version": "1.0",
        "classification": classification,
        "author_role": author_role,
        "reason": reason,
        "changes": changes,
        "created_at": created_at,
        "parent_constitution_hash": parent_constitution_hash,
    }
    return ConstitutionAmendment(**payload, amendment_hash=canonical_sha256(payload))
