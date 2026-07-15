"""Deterministic append-only SHA-256 audit log with verification and replay."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from quantforge.domain.models import AuditEvent, RoleName, WorkflowState
from quantforge.serialization.canonical import canonical_json, canonical_sha256
from quantforge.serialization.safe_json import safe_parse_json

GENESIS_HASH = "0" * 64


class AuditLog:
    def __init__(self, events: tuple[AuditEvent, ...] = ()) -> None:
        self._events = list(events)
        self.verify()

    @property
    def events(self) -> tuple[AuditEvent, ...]:
        return tuple(self._events)

    def append(
        self,
        *,
        timestamp: datetime,
        case_id: str,
        workflow_state: WorkflowState,
        actor: RoleName,
        action: str,
        payload: Any,
    ) -> AuditEvent:
        sequence = len(self._events) + 1
        previous_hash = self._events[-1].current_event_hash if self._events else GENESIS_HASH
        event_payload: dict[str, Any] = {
            "event_id": f"audit_{sequence:06d}",
            "schema_version": "1.0",
            "sequence": sequence,
            "timestamp": timestamp,
            "case_id": case_id,
            "workflow_state": workflow_state,
            "actor": actor,
            "action": action,
            "payload_hash": canonical_sha256(payload),
            "previous_event_hash": previous_hash,
        }
        event = AuditEvent(**event_payload, current_event_hash=canonical_sha256(event_payload))
        self._events.append(event)
        return event

    def verify(self) -> None:
        previous_hash = GENESIS_HASH
        for expected_sequence, event in enumerate(self._events, start=1):
            if event.sequence != expected_sequence:
                raise ValueError("audit sequence gap or reordering detected")
            if event.previous_event_hash != previous_hash:
                raise ValueError("audit previous-hash mismatch")
            payload = event.model_dump(mode="python", exclude={"current_event_hash"})
            if canonical_sha256(payload) != event.current_event_hash:
                raise ValueError("audit event tampering detected")
            previous_hash = event.current_event_hash

    def replay_states(self) -> tuple[WorkflowState, ...]:
        self.verify()
        return tuple(event.workflow_state for event in self._events)

    def write_jsonl(self, path: Path) -> None:
        if path.exists() and path.is_symlink():
            raise ValueError("refusing to replace a symlink")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(canonical_json(event) + "\n" for event in self._events), encoding="utf-8"
        )

    @classmethod
    def read_jsonl(cls, path: Path, *, max_bytes: int = 2_000_000) -> AuditLog:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
            raise ValueError("audit input must be a bounded regular file")
        events: list[AuditEvent] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                raise ValueError(f"empty audit record at line {line_number}")
            try:
                value = safe_parse_json(line)
                events.append(AuditEvent.model_validate_json(canonical_json(value)))
            except ValueError as error:
                raise ValueError(f"invalid audit record at line {line_number}") from error
        return cls(tuple(events))
