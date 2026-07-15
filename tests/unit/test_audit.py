from __future__ import annotations

import os
from pathlib import Path

import pytest

from quantforge.audit import AuditLog
from quantforge.workflow.demo import run_demo


def test_audit_chain_verifies_replays_and_roundtrips(tmp_path: Path) -> None:
    log = run_demo("provisional").audit_log
    log.verify()
    assert len(log.replay_states()) == 12
    path = tmp_path / "audit.jsonl"
    log.write_jsonl(path)
    restored = AuditLog.read_jsonl(path)
    assert restored.events == log.events


@pytest.mark.parametrize("mutation", ["delete", "reorder", "hash", "previous", "sequence"])
def test_audit_detects_tampering(mutation: str) -> None:
    events = list(run_demo("provisional").audit_log.events)
    if mutation == "delete":
        del events[3]
    elif mutation == "reorder":
        events[3], events[4] = events[4], events[3]
    elif mutation == "hash":
        events[3] = events[3].model_copy(update={"current_event_hash": "f" * 64})
    elif mutation == "previous":
        events[3] = events[3].model_copy(update={"previous_event_hash": "f" * 64})
    else:
        events[3] = events[3].model_copy(update={"sequence": 99})
    with pytest.raises(ValueError, match="audit"):
        AuditLog(tuple(events))


def test_audit_input_and_output_controls(tmp_path: Path) -> None:
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
    empty.write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty audit"):
        AuditLog.read_jsonl(empty)
    link = tmp_path / "link.jsonl"
    os.symlink(path, link)
    with pytest.raises(ValueError, match="bounded"):
        AuditLog.read_jsonl(link)
    with pytest.raises(ValueError, match="symlink"):
        log.write_jsonl(link)
