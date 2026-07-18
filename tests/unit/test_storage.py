from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast

import pytest

from quantforge.audit import AuditLog
from quantforge.domain.models import WorkflowState
from quantforge.serialization.canonical import canonical_json, canonical_sha256
from quantforge.serialization.safe_json import safe_load_json
from quantforge.storage import CaseStore, DurableCase, SQLiteCaseStore, persist_audited_case
from quantforge.storage.sqlite import (
    _SCHEMA_FINGERPRINTS,
    LATEST_SCHEMA_VERSION,
    MIGRATIONS,
    RevisionConflictError,
)
from quantforge.workflow.demo import run_demo


def _initialized_store(path: Path) -> SQLiteCaseStore:
    store = SQLiteCaseStore(path)
    inspection = store.initialize()
    assert inspection.schema_version == LATEST_SCHEMA_VERSION
    return store


def test_case_store_abstract_defaults_fail_closed() -> None:
    receiver = cast(CaseStore, None)
    unknown = cast(Any, None)
    getter = cast(Any, CaseStore.path).fget
    assert getter is not None
    calls = (
        lambda: getter(receiver),
        lambda: CaseStore.initialize(receiver),
        lambda: CaseStore.inspect(receiver),
        lambda: CaseStore.migrate(receiver, dry_run=True),
        lambda: CaseStore.create_case(receiver, unknown, unknown),
        lambda: CaseStore.append_event(receiver, unknown, expected_revision=1),
        lambda: CaseStore.record_provider_invocation(
            receiver,
            unknown,
            None,
            expected_revision=1,
        ),
        lambda: CaseStore.find_accepted_provider_invocation(
            receiver,
            "case",
            case_revision=1,
            action=unknown,
        ),
        lambda: CaseStore.list_provider_invocations(receiver, "case"),
        lambda: CaseStore.admit_evidence_bundle(receiver, unknown, unknown, expected_revision=1),
        lambda: CaseStore.save_claim_graph(receiver, "case", unknown, expected_revision=1),
        lambda: CaseStore.list_evidence_bundles(receiver, "case"),
        lambda: CaseStore.find_export(receiver, "case", "export"),
        lambda: CaseStore.latest_export(receiver, "case"),
        lambda: CaseStore.record_export(
            receiver,
            "case",
            unknown,
            expected_revision=1,
            created_at=unknown,
        ),
        lambda: CaseStore.reconstruct(receiver, "case"),
        lambda: CaseStore.verify(receiver),
    )
    for call in calls:
        with pytest.raises(NotImplementedError):
            call()


def _persist_complete(path: Path) -> tuple[SQLiteCaseStore, DurableCase]:
    store = _initialized_store(path)
    result = run_demo("provisional")
    durable = persist_audited_case(store, result.audit_log, claim_graph=result.claim_graph)
    return store, durable


def test_durable_case_round_trip_materializes_every_governed_record(tmp_path: Path) -> None:
    store, durable = _persist_complete(tmp_path / "cases.sqlite3")
    result = run_demo("provisional")
    assert durable.case == result.case
    assert durable.audit_log.events == result.audit_log.events
    assert durable.evidence_ledger is not None
    assert durable.evidence_ledger.snapshot() == result.evidence_ledger.snapshot()
    assert durable.claim_graph is not None
    assert durable.claim_graph.snapshot() == result.claim_graph.snapshot()
    assert durable.revision == 12
    assert durable.semantic_hash == canonical_sha256(result.case)
    assert store.verify().event_count == 12

    connection = sqlite3.connect(store.path)
    try:
        assert connection.execute("SELECT count(*) FROM constitutions").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM evidence_records").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM claim_graphs").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM reviewer_outputs").fetchone()[0] == 5
        assert connection.execute("SELECT count(*) FROM verdict_results").fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchone() is None
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        connection.close()


def test_atomic_creation_and_immutable_identifiers(tmp_path: Path) -> None:
    store = _initialized_store(tmp_path / "cases.sqlite3")
    result = run_demo("fragile")
    first_case = result.audit_log.replay_cases(require_complete=False)[0]
    first_event = result.audit_log.events[0]
    assert store.create_case(first_case, first_event) == 1
    with pytest.raises(ValueError, match="cannot be overwritten"):
        store.create_case(first_case, first_event)
    assert store.inspect().case_count == 1
    with pytest.raises(ValueError, match="first audit"):
        store.create_case(first_case, result.audit_log.events[1])


def test_optimistic_revision_conflicts_are_serialized(tmp_path: Path) -> None:
    store = _initialized_store(tmp_path / "cases.sqlite3")
    result = run_demo("inconclusive")
    cases = result.audit_log.replay_cases(require_complete=False)
    events = result.audit_log.events
    store.create_case(cases[0], events[0])

    def append() -> int:
        return store.append_event(events[1], expected_revision=1)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(append) for _ in range(2)]
    outcomes: list[object] = []
    for future in futures:
        try:
            outcomes.append(future.result())
        except RevisionConflictError as error:
            outcomes.append(error)
    assert sum(item == 2 for item in outcomes) == 1
    assert sum(isinstance(item, RevisionConflictError) for item in outcomes) == 1
    assert store.reconstruct(cases[0].case_id).revision == 2


def test_sql_injection_text_is_only_a_parameter(tmp_path: Path) -> None:
    store, _ = _persist_complete(tmp_path / "cases.sqlite3")
    with pytest.raises(ValueError, match="unknown case"):
        store.reconstruct("case_provisional' OR 1=1 --")
    assert store.inspect().case_count == 1


def test_payload_and_audit_chain_corruption_fail_closed(tmp_path: Path) -> None:
    store, _ = _persist_complete(tmp_path / "cases.sqlite3")
    connection = sqlite3.connect(store.path)
    try:
        connection.execute(
            "UPDATE audit_events SET payload_json = ? WHERE case_id = ? AND sequence = 2",
            ('{"substituted":true}', "case_provisional"),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises((ValueError, TypeError), match=r"payload|validation|Field|required"):
        store.reconstruct("case_provisional")


@pytest.mark.parametrize(
    "mutation",
    [
        "delete_graph",
        "alter_graph",
        "delete_reviewer",
        "alter_review",
        "alter_verdict",
        "workflow_state",
        "clear_finalization",
        "revision",
        "schema_version",
        "updated_at",
        "semantic_hash",
        "audit_head",
        "partial_graph_anchor",
        "extra_graph",
    ],
)
@pytest.mark.malicious
def test_authoritative_materialization_mutations_fail_closed(tmp_path: Path, mutation: str) -> None:
    store, _ = _persist_complete(tmp_path / f"{mutation}.sqlite3")
    connection = sqlite3.connect(store.path)
    try:
        if mutation == "delete_graph":
            connection.execute("DELETE FROM claim_graphs WHERE case_id = ?", ("case_provisional",))
        elif mutation == "alter_graph":
            row = connection.execute(
                "SELECT payload_json FROM claim_graphs WHERE case_id = ?",
                ("case_provisional",),
            ).fetchone()
            assert row is not None
            value = _parse_json_object(str(row[0]))
            nodes = value["nodes"]
            assert isinstance(nodes, list) and isinstance(nodes[0], dict)
            nodes[0]["substantive_final_claim"] = not bool(nodes[0]["substantive_final_claim"])
            connection.execute(
                "UPDATE claim_graphs SET payload_json = ?, payload_hash = ? WHERE case_id = ?",
                (canonical_json(value), canonical_sha256(value), "case_provisional"),
            )
        elif mutation == "delete_reviewer":
            connection.execute(
                "DELETE FROM reviewer_outputs WHERE case_id = ? AND revision = 7",
                ("case_provisional",),
            )
        elif mutation == "alter_review":
            row = connection.execute(
                "SELECT payload_json FROM reviewer_outputs WHERE case_id = ? AND revision = 7",
                ("case_provisional",),
            ).fetchone()
            assert row is not None
            value = _parse_json_object(str(row[0]))
            value["review_id"] = "statistics_substituted"
            connection.execute(
                """
                UPDATE reviewer_outputs SET payload_json = ?, payload_hash = ?
                WHERE case_id = ? AND revision = 7
                """,
                (canonical_json(value), canonical_sha256(value), "case_provisional"),
            )
        elif mutation == "alter_verdict":
            row = connection.execute(
                "SELECT payload_json FROM verdict_results WHERE case_id = ?",
                ("case_provisional",),
            ).fetchone()
            assert row is not None
            value = _parse_json_object(str(row[0]))
            value["decisive_reasons"] = ["substituted but valid narrative"]
            connection.execute(
                "UPDATE verdict_results SET payload_json = ?, payload_hash = ? WHERE case_id = ?",
                (canonical_json(value), canonical_sha256(value), "case_provisional"),
            )
        elif mutation == "workflow_state":
            connection.execute(
                "UPDATE cases SET state = ? WHERE case_id = ?",
                (WorkflowState.VERDICT_ELIGIBILITY_COMPUTED.value, "case_provisional"),
            )
        elif mutation == "clear_finalization":
            connection.execute(
                "UPDATE cases SET finalized = 0 WHERE case_id = ?", ("case_provisional",)
            )
        elif mutation == "revision":
            connection.execute(
                "UPDATE cases SET revision = 11 WHERE case_id = ?", ("case_provisional",)
            )
        elif mutation == "schema_version":
            connection.execute(
                "UPDATE cases SET schema_version = ? WHERE case_id = ?",
                ("9.9", "case_provisional"),
            )
        elif mutation == "updated_at":
            connection.execute(
                "UPDATE cases SET updated_at_utc = created_at_utc WHERE case_id = ?",
                ("case_provisional",),
            )
        elif mutation == "semantic_hash":
            connection.execute(
                "UPDATE cases SET semantic_hash = ? WHERE case_id = ?",
                ("1" * 64, "case_provisional"),
            )
        elif mutation == "audit_head":
            connection.execute(
                "UPDATE cases SET audit_head_hash = ? WHERE case_id = ?",
                ("2" * 64, "case_provisional"),
            )
        elif mutation == "partial_graph_anchor":
            connection.execute(
                "UPDATE cases SET graph_hash = NULL WHERE case_id = ?",
                ("case_provisional",),
            )
        else:
            row = connection.execute(
                "SELECT payload_json, payload_hash FROM claim_graphs WHERE case_id = ?",
                ("case_provisional",),
            ).fetchone()
            assert row is not None
            connection.execute(
                """
                INSERT INTO claim_graphs(case_id, revision, payload_json, payload_hash)
                VALUES (?, 11, ?, ?)
                """,
                ("case_provisional", str(row[0]), str(row[1])),
            )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises((ValueError, TypeError)):
        store.reconstruct("case_provisional", require_complete=False)


def _parse_json_object(payload: str) -> dict[str, object]:
    value = json.loads(payload)
    assert isinstance(value, dict)
    return value


def test_unknown_schema_objects_and_partial_migrations_are_rejected(tmp_path: Path) -> None:
    first = _initialized_store(tmp_path / "trigger.sqlite3")
    connection = sqlite3.connect(first.path)
    try:
        connection.execute("CREATE TRIGGER hostile AFTER INSERT ON cases BEGIN SELECT 1; END")
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(ValueError, match=r"schema objects|fingerprint"):
        first.inspect()

    second = _initialized_store(tmp_path / "partial.sqlite3")
    connection = sqlite3.connect(second.path)
    try:
        connection.execute("UPDATE store_metadata SET schema_version = 1")
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(ValueError, match="partial"):
        second.migrate()


def test_future_malformed_and_oversized_databases_are_rejected(tmp_path: Path) -> None:
    future = _initialized_store(tmp_path / "future.sqlite3")
    connection = sqlite3.connect(future.path)
    try:
        connection.execute("PRAGMA user_version=999")
    finally:
        connection.close()
    with pytest.raises(ValueError, match="future"):
        future.inspect()

    malformed = tmp_path / "malformed.sqlite3"
    malformed.write_bytes(b"not a sqlite database")
    with pytest.raises(sqlite3.DatabaseError):
        SQLiteCaseStore(malformed).inspect()

    oversized = tmp_path / "oversized.sqlite3"
    with oversized.open("wb") as stream:
        stream.truncate(65 * 1024 * 1024)
    with pytest.raises(ValueError, match="resource limit"):
        SQLiteCaseStore(oversized).inspect()


def test_store_and_database_paths_reject_symlinks(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        SQLiteCaseStore(linked / "cases.sqlite3").initialize()

    store = _initialized_store(tmp_path / "source.sqlite3")
    link = tmp_path / "cases-link.sqlite3"
    link.symlink_to(store.path)
    with pytest.raises(ValueError, match="symlink"):
        SQLiteCaseStore(link).inspect()


@pytest.mark.parametrize("suffix", ["-wal", "-shm"])
@pytest.mark.malicious
def test_hostile_database_sidecars_are_bounded(tmp_path: Path, suffix: str) -> None:
    store = _initialized_store(tmp_path / "cases.sqlite3")
    sidecar = Path(f"{store.path}{suffix}")
    target = tmp_path / "sidecar-target"
    target.write_bytes(b"hostile")
    sidecar.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        store.inspect()
    sidecar.unlink()
    with sidecar.open("wb") as stream:
        stream.truncate(65 * 1024 * 1024)
    with pytest.raises(ValueError, match="resource limit"):
        store.inspect()


def test_database_replacement_during_reconstruction_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = _persist_complete(tmp_path / "cases.sqlite3")
    connection = sqlite3.connect(store.path)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()
    replacement = tmp_path / "replacement.sqlite3"
    shutil.copyfile(store.path, replacement)
    original = store._load_events
    replaced = False

    def replace_after_read(connection: sqlite3.Connection, case_id: str) -> tuple[object, ...]:
        nonlocal replaced
        events = original(connection, case_id)
        if not replaced:
            try:
                os.replace(replacement, store.path)
            except PermissionError:
                if os.name != "nt":
                    raise
                raise ValueError("case-store database replacement was blocked by the OS") from None
            replaced = True
        return events

    monkeypatch.setattr(store, "_load_events", replace_after_read)
    with pytest.raises(ValueError, match=r"replaced|replacement was blocked"):
        store.reconstruct("case_provisional")


def test_post_finalization_event_injection_is_rejected(tmp_path: Path) -> None:
    store, _ = _persist_complete(tmp_path / "cases.sqlite3")
    event = run_demo("provisional").audit_log.events[-1]
    with pytest.raises(ValueError, match="finalized"):
        store.append_event(event, expected_revision=12)


@pytest.mark.parametrize("source_version", [1, 2])
def test_frozen_historical_migration_preserves_semantics(
    tmp_path: Path, source_version: int
) -> None:
    fixture_root = Path(__file__).parents[1] / f"fixtures/storage/schema{source_version}"
    metadata = safe_load_json(fixture_root / "metadata.json")
    source = fixture_root / "provisional_case.sqlite3"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == metadata["database_sha256"]
    assert _SCHEMA_FINGERPRINTS[source_version] == metadata["schema_fingerprint"]
    assert {
        str(migration.version): migration.checksum for migration in MIGRATIONS[:source_version]
    } == metadata["migration_checksums"]
    target = tmp_path / f"schema{source_version}.sqlite3"
    shutil.copyfile(source, target)
    store = SQLiteCaseStore(target)
    assert store.inspect().schema_version == source_version
    dry_run = store.migrate(dry_run=True)
    assert dry_run.schema_version == LATEST_SCHEMA_VERSION
    assert dry_run.integrity == "dry_run_passed"
    assert store.inspect().schema_version == source_version

    migrated = store.migrate()
    assert migrated.schema_version == LATEST_SCHEMA_VERSION
    reconstructed = store.reconstruct(str(metadata["case_id"]), require_complete=True)
    assert reconstructed.revision == metadata["revision"]
    assert reconstructed.semantic_hash == metadata["semantic_hash"]
    assert reconstructed.audit_head_hash == metadata["audit_head_hash"]
    assert reconstructed.graph_revision == metadata["revision"]
    assert reconstructed.graph_hash == metadata["graph_hash"]
    assert store.verify().integrity == "passed"
    assert store.migrate().schema_version == LATEST_SCHEMA_VERSION


def test_empty_unknown_and_invalid_operations_fail_closed(tmp_path: Path) -> None:
    store = _initialized_store(tmp_path / "cases.sqlite3")
    with pytest.raises(ValueError, match="unknown case"):
        store.reconstruct("case_missing")
    with pytest.raises(ValueError, match="already exists"):
        store.initialize()
    with pytest.raises(ValueError, match="timeout"):
        SQLiteCaseStore(tmp_path / "other.sqlite3", busy_timeout_ms=0)
    with pytest.raises(ValueError, match="unversioned"):
        path = tmp_path / "foreign.sqlite3"
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE foreign_table(value TEXT)")
        connection.close()
        SQLiteCaseStore(path).migrate()


def test_incomplete_audit_can_be_persisted_and_reconstructed(tmp_path: Path) -> None:
    result = run_demo("fragile")
    prefix = AuditLog(result.audit_log.events[:5])
    store = _initialized_store(tmp_path / "cases.sqlite3")
    durable = persist_audited_case(store, prefix)
    assert durable.revision == 5
    assert durable.case.state is WorkflowState.CONSTITUTION_LOCKED
    with pytest.raises(ValueError, match="incomplete"):
        store.reconstruct(durable.case.case_id, require_complete=True)
