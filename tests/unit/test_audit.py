from __future__ import annotations

import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from quantforge.audit import AuditLog
from quantforge.domain.models import AuditEvent, RoleName, WorkflowState
from quantforge.serialization.canonical import canonical_json, canonical_sha256
from quantforge.workflow.demo import run_demo


def test_audit_chain_verifies_reconstructs_and_roundtrips(tmp_path: Path) -> None:
    result = run_demo("provisional")
    log = result.audit_log
    log.verify(require_complete=True)
    assert len(log.replay_states()) == 12
    assert log.replay_case() == result.case
    path = tmp_path / "audit.jsonl"
    log.write_jsonl(path)
    restored = AuditLog.read_jsonl(path)
    assert restored.events == log.events
    assert restored.replay_case() == result.case


@pytest.mark.parametrize(
    "mutation",
    [
        "delete",
        "reorder",
        "duplicate",
        "hash",
        "previous",
        "sequence",
        "payload",
        "timestamp",
        "actor",
        "case",
    ],
)
def test_audit_detects_tampering(mutation: str) -> None:
    events = list(run_demo("provisional").audit_log.events)

    def tamper(field: str, value: object) -> None:
        event = events[3].model_copy()
        object.__setattr__(event, field, value)
        events[3] = event

    if mutation == "delete":
        del events[3]
    elif mutation == "reorder":
        events[3], events[4] = events[4], events[3]
    elif mutation == "duplicate":
        events.insert(3, events[3])
    elif mutation == "hash":
        tamper("current_event_hash", "f" * 64)
    elif mutation == "previous":
        tamper("previous_event_hash", "f" * 64)
    elif mutation == "sequence":
        tamper("sequence", 99)
    elif mutation == "payload":
        tamper("payload", {"tampered": True})
    elif mutation == "timestamp":
        tamper("timestamp", datetime(2020, 1, 1, tzinfo=UTC))
    elif mutation == "actor":
        tamper("actor", RoleName.TRIBUNAL_CHAIR)
    else:
        tamper("case_id", "case_other")
    with pytest.raises((PermissionError, ValueError), match=r"audit|authorized|cases|timestamps"):
        AuditLog(tuple(events))


def test_audit_rejects_cross_case_append() -> None:
    result = run_demo("provisional")
    proposal = result.case.proposal
    assert proposal is not None
    prefix = AuditLog(result.audit_log.events[:1])
    with pytest.raises(ValueError, match="different cases"):
        prefix.append(
            timestamp=datetime(2027, 1, 1, tzinfo=UTC),
            case_id="case_other",
            workflow_state=WorkflowState.RESEARCHER_PROTOCOL_PROPOSED,
            actor=RoleName.RESEARCHER,
            action="propose_protocol",
            payload=proposal,
        )


def test_rehashed_policy_input_tampering_is_rejected_semantically() -> None:
    events = list(run_demo("provisional").audit_log.events)
    verdict_index = 10
    verdict_data = deepcopy(events[verdict_index].model_dump(mode="python"))
    assert isinstance(verdict_data["payload"], dict)
    assert isinstance(verdict_data["payload"]["inputs"], dict)
    verdict_data["payload"]["inputs"]["primary_experiment_complete"] = False
    previous_hash = events[verdict_index - 1].current_event_hash
    for index in range(verdict_index, len(events)):
        data = (
            verdict_data
            if index == verdict_index
            else deepcopy(events[index].model_dump(mode="python"))
        )
        data["previous_event_hash"] = previous_hash
        data["payload_hash"] = canonical_sha256(data["payload"])
        data["current_event_hash"] = canonical_sha256(
            {key: value for key, value in data.items() if key != "current_event_hash"}
        )
        events[index] = AuditEvent.model_validate(data)
        previous_hash = events[index].current_event_hash
    with pytest.raises(ValueError, match="not derived"):
        AuditLog(tuple(events))


def test_rehashed_future_domain_timestamp_is_rejected_semantically() -> None:
    events = list(run_demo("provisional").audit_log.events)
    proposal_index = 1
    proposal_data = deepcopy(events[proposal_index].model_dump(mode="python"))
    assert isinstance(proposal_data["payload"], dict)
    future = events[proposal_index].timestamp + timedelta(seconds=1)
    proposal_data["payload"]["proposed_at"] = future.isoformat().replace("+00:00", "Z")
    previous_hash = events[proposal_index - 1].current_event_hash
    for index in range(proposal_index, len(events)):
        data = (
            proposal_data
            if index == proposal_index
            else deepcopy(events[index].model_dump(mode="python"))
        )
        data["previous_event_hash"] = previous_hash
        data["payload_hash"] = canonical_sha256(data["payload"])
        data["current_event_hash"] = canonical_sha256(
            {key: value for key, value in data.items() if key != "current_event_hash"}
        )
        events[index] = AuditEvent.model_validate(data)
        previous_hash = events[index].current_event_hash
    with pytest.raises(ValueError, match="postdates"):
        AuditLog(tuple(events))


def test_audit_input_output_truncation_and_suffix_controls(tmp_path: Path) -> None:
    log = run_demo("provisional").audit_log
    path = tmp_path / "audit.jsonl"
    log.write_jsonl(path)
    with pytest.raises(ValueError, match="bounded"):
        AuditLog.read_jsonl(path, max_bytes=1)
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid audit record"):
        AuditLog.read_jsonl(bad)
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot be empty"):
        AuditLog.read_jsonl(empty)
    truncated = tmp_path / "truncated.jsonl"
    truncated.write_text(
        "".join(canonical_json(event) + "\n" for event in log.events[:-1]),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="incomplete prefix"):
        AuditLog.read_jsonl(truncated)
    malicious_suffix = tmp_path / "suffix.jsonl"
    malicious_suffix.write_text(path.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid audit record"):
        AuditLog.read_jsonl(malicious_suffix)
    link = tmp_path / "link.jsonl"
    os.symlink(path, link)
    with pytest.raises(ValueError, match="symlink"):
        AuditLog.read_jsonl(link)
    with pytest.raises(ValueError, match="symlink"):
        log.write_jsonl(link)
