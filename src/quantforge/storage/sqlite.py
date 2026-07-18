"""Crash-safe SQLite implementation of the governed case-store contract."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from quantforge.audit import AuditLog
from quantforge.domain.models import (
    AuditEvent,
    EvidenceObject,
    ExperimentConstitution,
    TribunalCase,
    WorkflowState,
)
from quantforge.engine.trust import _TrustedAdmissionCapability
from quantforge.evidence.bundle import EvidenceBundle
from quantforge.evidence.graph import ClaimGraph, ClaimGraphSnapshot
from quantforge.evidence.ledger import EvidenceLedger, EvidenceLedgerSnapshot
from quantforge.roles.contracts import RoleAction
from quantforge.serialization.canonical import canonical_json, canonical_sha256
from quantforge.serialization.safe_json import reject_symlink_components, safe_parse_json
from quantforge.storage.base import (
    CaseStore,
    DurableCase,
    ExportRecord,
    ProviderInvocationRecord,
    ProviderInvocationStatus,
    StoreInspection,
)

LATEST_SCHEMA_VERSION: Final = 4
APPLICATION_ID: Final = 0x51464F52
MAX_DATABASE_BYTES: Final = 64 * 1024 * 1024
MAX_WAL_BYTES: Final = 64 * 1024 * 1024
MAX_SHM_BYTES: Final = 16 * 1024 * 1024
MAX_CASES: Final = 10_000
MAX_EVENTS_PER_CASE: Final = 10_000
MAX_CANONICAL_PAYLOAD_BYTES: Final = 2_000_000


class RevisionConflictError(ValueError):
    """Raised when a writer uses a stale optimistic revision."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]

    @property
    def checksum(self) -> str:
        return canonical_sha256(
            {"name": self.name, "statements": self.statements, "version": self.version}
        )


MIGRATIONS: Final = (
    Migration(
        1,
        "governed_case_core",
        (
            f"PRAGMA application_id={APPLICATION_ID}",
            """
            CREATE TABLE store_metadata (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                store_id TEXT NOT NULL UNIQUE,
                schema_version INTEGER NOT NULL CHECK (schema_version >= 1),
                created_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TABLE migration_history (
                version INTEGER PRIMARY KEY CHECK (version >= 1),
                name TEXT NOT NULL UNIQUE,
                checksum TEXT NOT NULL CHECK (length(checksum) = 64),
                applied_at_utc TEXT NOT NULL
            ) STRICT
            """,
            """
            CREATE TABLE cases (
                case_id TEXT PRIMARY KEY,
                schema_version TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision >= 1),
                state TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL,
                semantic_hash TEXT NOT NULL CHECK (length(semantic_hash) = 64),
                audit_head_hash TEXT NOT NULL CHECK (length(audit_head_hash) = 64),
                finalized INTEGER NOT NULL CHECK (finalized IN (0, 1))
            ) STRICT
            """,
            """
            CREATE TABLE audit_events (
                case_id TEXT NOT NULL,
                sequence INTEGER NOT NULL CHECK (sequence >= 1),
                event_id TEXT NOT NULL,
                timestamp_utc TEXT NOT NULL,
                workflow_state TEXT NOT NULL,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                payload_json TEXT NOT NULL CHECK (length(payload_json) <= 2000000),
                payload_hash TEXT NOT NULL CHECK (length(payload_hash) = 64),
                previous_event_hash TEXT NOT NULL CHECK (length(previous_event_hash) = 64),
                current_event_hash TEXT NOT NULL CHECK (length(current_event_hash) = 64),
                PRIMARY KEY (case_id, sequence),
                UNIQUE (case_id, event_id),
                FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE RESTRICT
            ) STRICT
            """,
            """
            CREATE TABLE constitutions (
                case_id TEXT PRIMARY KEY,
                constitution_id TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision >= 1),
                payload_json TEXT NOT NULL CHECK (length(payload_json) <= 2000000),
                payload_hash TEXT NOT NULL CHECK (length(payload_hash) = 64),
                FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE RESTRICT,
                UNIQUE (case_id, constitution_id)
            ) STRICT
            """,
            """
            CREATE TABLE evidence_bundles (
                case_id TEXT NOT NULL,
                bundle_sequence INTEGER NOT NULL CHECK (bundle_sequence >= 1),
                bundle_id TEXT NOT NULL,
                workflow_revision INTEGER NOT NULL CHECK (workflow_revision >= 1),
                bundle_json TEXT NOT NULL CHECK (length(bundle_json) <= 2000000),
                bundle_hash TEXT NOT NULL CHECK (length(bundle_hash) = 64),
                previous_bundle_hash TEXT NOT NULL CHECK (length(previous_bundle_hash) = 64),
                observed_at_utc TEXT NOT NULL,
                signature_json TEXT,
                PRIMARY KEY (case_id, bundle_sequence),
                UNIQUE (bundle_id),
                UNIQUE (bundle_hash),
                UNIQUE (case_id, bundle_id),
                FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE RESTRICT
            ) STRICT
            """,
            """
            CREATE TABLE bundle_artifacts (
                case_id TEXT NOT NULL,
                bundle_id TEXT NOT NULL,
                direction TEXT NOT NULL CHECK (direction IN ('input', 'output')),
                artifact_path TEXT NOT NULL,
                byte_sha256 TEXT NOT NULL CHECK (length(byte_sha256) = 64),
                semantic_sha256 TEXT NOT NULL CHECK (length(semantic_sha256) = 64),
                size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
                schema_version TEXT NOT NULL,
                PRIMARY KEY (case_id, bundle_id, direction, artifact_path),
                FOREIGN KEY (case_id, bundle_id)
                    REFERENCES evidence_bundles(case_id, bundle_id) ON DELETE RESTRICT
            ) STRICT
            """,
            """
            CREATE TABLE evidence_records (
                case_id TEXT NOT NULL,
                evidence_id TEXT NOT NULL,
                bundle_id TEXT,
                revision INTEGER NOT NULL CHECK (revision >= 1),
                payload_json TEXT NOT NULL CHECK (length(payload_json) <= 2000000),
                payload_hash TEXT NOT NULL CHECK (length(payload_hash) = 64),
                PRIMARY KEY (case_id, evidence_id),
                FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE RESTRICT,
                FOREIGN KEY (case_id, bundle_id)
                    REFERENCES evidence_bundles(case_id, bundle_id) ON DELETE RESTRICT
            ) STRICT
            """,
            """
            CREATE TABLE claim_graphs (
                case_id TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision >= 1),
                payload_json TEXT NOT NULL CHECK (length(payload_json) <= 2000000),
                payload_hash TEXT NOT NULL CHECK (length(payload_hash) = 64),
                PRIMARY KEY (case_id, revision),
                FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE RESTRICT
            ) STRICT
            """,
            """
            CREATE TABLE reviewer_outputs (
                case_id TEXT NOT NULL,
                review_id TEXT NOT NULL,
                reviewer_role TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision >= 1),
                payload_json TEXT NOT NULL CHECK (length(payload_json) <= 2000000),
                payload_hash TEXT NOT NULL CHECK (length(payload_hash) = 64),
                PRIMARY KEY (case_id, review_id),
                FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE RESTRICT
            ) STRICT
            """,
            """
            CREATE TABLE verdict_results (
                case_id TEXT PRIMARY KEY,
                eligibility_id TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision >= 1),
                payload_json TEXT NOT NULL CHECK (length(payload_json) <= 2000000),
                payload_hash TEXT NOT NULL CHECK (length(payload_hash) = 64),
                FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE RESTRICT
            ) STRICT
            """,
            """
            CREATE INDEX audit_events_state_idx
            ON audit_events(case_id, workflow_state, sequence)
            """,
            "CREATE INDEX bundles_revision_idx ON evidence_bundles(case_id, workflow_revision)",
        ),
    ),
    Migration(
        2,
        "deterministic_export_lineage",
        (
            """
            CREATE TABLE exports (
                case_id TEXT NOT NULL,
                export_id TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision >= 1),
                parent_manifest_hash TEXT NOT NULL CHECK (length(parent_manifest_hash) = 64),
                manifest_json TEXT NOT NULL CHECK (length(manifest_json) <= 2000000),
                manifest_hash TEXT NOT NULL CHECK (length(manifest_hash) = 64),
                created_at_utc TEXT NOT NULL,
                PRIMARY KEY (case_id, export_id),
                UNIQUE (manifest_hash),
                FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE RESTRICT
            ) STRICT
            """,
            """
            CREATE TABLE export_artifacts (
                case_id TEXT NOT NULL,
                export_id TEXT NOT NULL,
                artifact_path TEXT NOT NULL,
                artifact_hash TEXT NOT NULL CHECK (length(artifact_hash) = 64),
                PRIMARY KEY (case_id, export_id, artifact_path),
                FOREIGN KEY (case_id, export_id)
                    REFERENCES exports(case_id, export_id) ON DELETE RESTRICT
            ) STRICT
            """,
            "CREATE INDEX exports_revision_idx ON exports(case_id, revision, export_id)",
        ),
    ),
    Migration(
        3,
        "claim_graph_revision_anchor",
        (
            (
                "ALTER TABLE cases ADD COLUMN graph_revision INTEGER "
                "CHECK (graph_revision IS NULL OR graph_revision >= 1)"
            ),
            (
                "ALTER TABLE cases ADD COLUMN graph_hash TEXT "
                "CHECK (graph_hash IS NULL OR length(graph_hash) = 64)"
            ),
            """
            UPDATE cases
            SET graph_revision = (
                SELECT max(claim_graphs.revision) FROM claim_graphs
                WHERE claim_graphs.case_id = cases.case_id
            )
            WHERE EXISTS (
                SELECT 1 FROM claim_graphs WHERE claim_graphs.case_id = cases.case_id
            )
            """,
            """
            UPDATE cases
            SET graph_hash = (
                SELECT claim_graphs.payload_hash FROM claim_graphs
                WHERE claim_graphs.case_id = cases.case_id
                ORDER BY claim_graphs.revision DESC LIMIT 1
            )
            WHERE graph_revision IS NOT NULL
            """,
        ),
    ),
    Migration(
        4,
        "governed_provider_invocations",
        (
            """
            CREATE TABLE provider_invocations (
                case_id TEXT NOT NULL,
                invocation_id TEXT NOT NULL,
                case_revision INTEGER NOT NULL CHECK (case_revision >= 1),
                reviewer_role TEXT NOT NULL,
                role_action TEXT NOT NULL,
                request_semantic_hash TEXT NOT NULL CHECK (length(request_semantic_hash) = 64),
                status TEXT NOT NULL CHECK (status IN ('accepted', 'failed')),
                record_json TEXT NOT NULL CHECK (length(record_json) <= 2000000),
                record_hash TEXT NOT NULL CHECK (length(record_hash) = 64),
                recorded_at_utc TEXT NOT NULL,
                PRIMARY KEY (case_id, invocation_id),
                FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE RESTRICT
            ) STRICT
            """,
            """
            CREATE TABLE provider_attempts (
                case_id TEXT NOT NULL,
                invocation_id TEXT NOT NULL,
                attempt_index INTEGER NOT NULL CHECK (attempt_index BETWEEN 0 AND 2),
                observation_json TEXT NOT NULL CHECK (length(observation_json) <= 2000000),
                observation_hash TEXT NOT NULL CHECK (length(observation_hash) = 64),
                PRIMARY KEY (case_id, invocation_id, attempt_index),
                FOREIGN KEY (case_id, invocation_id)
                    REFERENCES provider_invocations(case_id, invocation_id) ON DELETE RESTRICT
            ) STRICT
            """,
            """
            CREATE UNIQUE INDEX provider_accepted_vote_idx
            ON provider_invocations(case_id, case_revision, reviewer_role, role_action)
            WHERE status = 'accepted'
            """,
            """
            CREATE INDEX provider_request_idx
            ON provider_invocations(case_id, request_semantic_hash, recorded_at_utc)
            """,
        ),
    ),
)

_EXPECTED_TABLES: Final = {
    1: {
        "audit_events",
        "bundle_artifacts",
        "cases",
        "claim_graphs",
        "constitutions",
        "evidence_bundles",
        "evidence_records",
        "migration_history",
        "reviewer_outputs",
        "store_metadata",
        "verdict_results",
    },
    2: {
        "audit_events",
        "bundle_artifacts",
        "cases",
        "claim_graphs",
        "constitutions",
        "evidence_bundles",
        "evidence_records",
        "export_artifacts",
        "exports",
        "migration_history",
        "reviewer_outputs",
        "store_metadata",
        "verdict_results",
    },
    3: {
        "audit_events",
        "bundle_artifacts",
        "cases",
        "claim_graphs",
        "constitutions",
        "evidence_bundles",
        "evidence_records",
        "export_artifacts",
        "exports",
        "migration_history",
        "reviewer_outputs",
        "store_metadata",
        "verdict_results",
    },
    4: {
        "audit_events",
        "bundle_artifacts",
        "cases",
        "claim_graphs",
        "constitutions",
        "evidence_bundles",
        "evidence_records",
        "export_artifacts",
        "exports",
        "migration_history",
        "provider_attempts",
        "provider_invocations",
        "reviewer_outputs",
        "store_metadata",
        "verdict_results",
    },
}


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("storage timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _now_utc_text() -> str:
    return _utc_text(datetime.now(UTC))


def _decode_model[ModelT](model_type: type[ModelT], payload: str) -> ModelT:
    value = safe_parse_json(payload, max_bytes=MAX_CANONICAL_PAYLOAD_BYTES)
    return model_type.model_validate_json(canonical_json(value))  # type: ignore[attr-defined,no-any-return]


def _schema_objects(connection: sqlite3.Connection) -> tuple[tuple[str, str, str, str], ...]:
    rows = connection.execute(
        """
        SELECT type, name, tbl_name, sql
        FROM sqlite_master
        WHERE name NOT LIKE 'sqlite_%'
        ORDER BY type, name
        """
    ).fetchall()
    return tuple((str(row[0]), str(row[1]), str(row[2]), str(row[3])) for row in rows)


def _expected_fingerprint(version: int) -> str:
    connection = sqlite3.connect(":memory:")
    try:
        for migration in MIGRATIONS:
            if migration.version > version:
                break
            for statement in migration.statements:
                connection.execute(statement)
        return canonical_sha256(_schema_objects(connection))
    finally:
        connection.close()


_SCHEMA_FINGERPRINTS: Final = {
    version: _expected_fingerprint(version) for version in range(1, LATEST_SCHEMA_VERSION + 1)
}


class SQLiteCaseStore(CaseStore):
    """SQLite backend with forward-only migrations and fail-closed verification."""

    def __init__(self, path: Path, *, busy_timeout_ms: int = 5_000) -> None:
        if busy_timeout_ms < 1 or busy_timeout_ms > 60_000:
            raise ValueError("busy timeout is outside the supported bound")
        self._path = path.absolute()
        self._busy_timeout_ms = busy_timeout_ms

    @property
    def path(self) -> Path:
        return self._path

    def initialize(self) -> StoreInspection:
        reject_symlink_components(self._path.parent)
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        reject_symlink_components(self._path)
        if self._path.exists():
            raise ValueError("case store already exists")
        connection = self._open_raw(create=True)
        try:
            self._apply_migrations(connection, LATEST_SCHEMA_VERSION)
        finally:
            connection.close()
        with suppress(OSError):
            os.chmod(self._path, 0o600)
        return self.inspect()

    def inspect(self) -> StoreInspection:
        self._validate_sidecars()
        connection = self._open_raw(create=False)
        try:
            self._validate_schema(connection, allow_historical=True)
            return self._inspection(connection, integrity="passed")
        finally:
            connection.close()

    def migrate(self, *, dry_run: bool = False) -> StoreInspection:
        self._validate_sidecars()
        source = self._open_raw(create=False)
        try:
            current = self._validate_schema(source, allow_historical=True)
            if current == LATEST_SCHEMA_VERSION:
                return self._inspection(source, integrity="passed")
            if dry_run:
                target = sqlite3.connect(":memory:")
                try:
                    source.backup(target)
                    self._configure_connection(target)
                    self._apply_migrations(target, LATEST_SCHEMA_VERSION)
                    self._validate_schema(target)
                    return self._inspection(target, integrity="dry_run_passed")
                finally:
                    target.close()
            self._apply_migrations(source, LATEST_SCHEMA_VERSION)
            self._validate_schema(source)
            return self._inspection(source, integrity="passed")
        finally:
            source.close()

    def create_case(self, case: TribunalCase, event: AuditEvent) -> int:
        if event.sequence != 1 or event.case_id != case.case_id:
            raise ValueError("case creation requires its first audit event")
        audit = AuditLog((event,))
        if audit.replay_case(require_complete=False) != case:
            raise ValueError("case does not match its creation event")
        with self._transaction() as connection:
            count = int(connection.execute("SELECT count(*) FROM cases").fetchone()[0])
            if count >= MAX_CASES:
                raise ValueError("case-store case limit reached")
            payload_hash = canonical_sha256(case)
            timestamp = _utc_text(event.timestamp)
            try:
                connection.execute(
                    """
                    INSERT INTO cases(
                        case_id, schema_version, revision, state, created_at_utc,
                        updated_at_utc, semantic_hash, audit_head_hash, finalized
                    ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        case.case_id,
                        case.schema_version,
                        case.state.value,
                        timestamp,
                        timestamp,
                        payload_hash,
                        event.current_event_hash,
                        int(case.state is WorkflowState.CHAIR_EXPLANATION),
                    ),
                )
                self._insert_event(connection, event)
            except sqlite3.IntegrityError as error:
                raise ValueError(
                    "case identifiers and immutable records cannot be overwritten"
                ) from error
        return 1

    def append_event(self, event: AuditEvent, *, expected_revision: int) -> int:
        with self._transaction() as connection:
            return self._append_event_transaction(connection, event, expected_revision)

    def record_provider_invocation(
        self,
        record: ProviderInvocationRecord,
        event: AuditEvent | None,
        *,
        expected_revision: int,
        final_claim_graph: ClaimGraph | None = None,
    ) -> int:
        if record.case_revision != expected_revision:
            raise ValueError("provider invocation is bound to a foreign case revision")
        accepted = record.status is ProviderInvocationStatus.ACCEPTED
        if accepted != (event is not None):
            raise ValueError("only an accepted provider invocation may include a workflow event")
        if event is not None and (
            event.case_id != record.case_id or event.sequence != expected_revision + 1
        ):
            raise ValueError("provider workflow event is bound to a foreign case revision")
        is_final = event is not None and event.workflow_state is WorkflowState.CHAIR_EXPLANATION
        if is_final != (final_claim_graph is not None):
            raise ValueError("Chair provider transaction requires exactly one final claim graph")
        graph_snapshot: ClaimGraphSnapshot | None = None
        graph_hash: str | None = None
        if final_claim_graph is not None:
            durable = self._reconstruct(
                record.case_id,
                require_complete=False,
                allow_pending_final_graph=True,
            )
            if durable.revision != expected_revision or durable.evidence_ledger is None:
                raise RevisionConflictError(
                    "final graph is not bound to the current evidence revision"
                )
            final_claim_graph.validate_against_ledger(durable.evidence_ledger)
            final_claim_graph.validate_final_claim_traceability()
            graph_snapshot = final_claim_graph.snapshot()
            graph_hash = canonical_sha256(graph_snapshot)
        with self._transaction() as connection:
            self._require_revision(connection, record.case_id, expected_revision)
            self._insert_provider_invocation(connection, record)
            if event is None:
                return expected_revision
            revision = self._append_event_transaction(connection, event, expected_revision)
            if graph_snapshot is not None and graph_hash is not None:
                self._anchor_final_graph_transaction(
                    connection,
                    record.case_id,
                    revision,
                    graph_snapshot,
                    graph_hash,
                )
            return revision

    def find_accepted_provider_invocation(
        self,
        case_id: str,
        *,
        case_revision: int,
        action: RoleAction,
    ) -> ProviderInvocationRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT case_id, invocation_id, case_revision, reviewer_role, role_action,
                       request_semantic_hash, status, record_json, record_hash, recorded_at_utc
                FROM provider_invocations
                WHERE case_id = ? AND case_revision = ? AND role_action = ?
                      AND status = 'accepted'
                """,
                (case_id, case_revision, action.value),
            ).fetchone()
            if row is None:
                return None
            record = self._decode_provider_invocation(row)
            self._verify_provider_attempt_rows(connection, record)
            return record

    def list_provider_invocations(self, case_id: str) -> tuple[ProviderInvocationRecord, ...]:
        with self._connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM cases WHERE case_id = ?", (case_id,)
            ).fetchone()
            if exists is None:
                raise ValueError("unknown case identifier")
            rows = connection.execute(
                """
                SELECT case_id, invocation_id, case_revision, reviewer_role, role_action,
                       request_semantic_hash, status, record_json, record_hash, recorded_at_utc
                FROM provider_invocations
                WHERE case_id = ? ORDER BY recorded_at_utc, invocation_id
                """,
                (case_id,),
            ).fetchall()
            records = tuple(self._decode_provider_invocation(row) for row in rows)
            for record in records:
                self._verify_provider_attempt_rows(connection, record)
            return records

    def admit_evidence_bundle(
        self,
        bundle: EvidenceBundle,
        event: AuditEvent,
        *,
        expected_revision: int,
        capability: _TrustedAdmissionCapability | None = None,
    ) -> int:
        if event.workflow_state is not WorkflowState.EXPERIMENT_EXECUTED:
            raise ValueError("engine evidence admission requires an experiment-executed event")
        if (
            bundle.semantic.case_id != event.case_id
            or bundle.semantic.workflow_revision != expected_revision
        ):
            raise ValueError("evidence bundle is bound to a foreign case revision")
        if capability is None:
            raise ValueError("engine evidence admission requires a trusted execution receipt")
        capability.consume(bundle, event, expected_revision)
        with self._transaction() as connection:
            self._require_revision(connection, event.case_id, expected_revision)
            previous_row = connection.execute(
                """
                SELECT bundle_sequence, bundle_hash FROM evidence_bundles
                WHERE case_id = ? ORDER BY bundle_sequence DESC LIMIT 1
                """,
                (event.case_id,),
            ).fetchone()
            bundle_sequence = 1 if previous_row is None else int(previous_row[0]) + 1
            expected_parent = "0" * 64 if previous_row is None else str(previous_row[1])
            if bundle.semantic.previous_bundle_hash != expected_parent:
                raise ValueError("evidence bundle does not extend the durable bundle chain")
            self._insert_bundle(connection, bundle, bundle_sequence)
            return self._append_event_transaction(connection, event, expected_revision)

    def save_claim_graph(self, case_id: str, graph: ClaimGraph, *, expected_revision: int) -> None:
        durable = self._reconstruct(
            case_id,
            require_complete=False,
            allow_pending_final_graph=True,
        )
        if durable.revision != expected_revision:
            raise RevisionConflictError(
                f"revision conflict: expected {expected_revision}, found {durable.revision}"
            )
        if durable.evidence_ledger is None:
            raise ValueError("claim graphs require admitted workflow evidence")
        graph.validate_against_ledger(durable.evidence_ledger)
        graph.validate_final_claim_traceability()
        snapshot = graph.snapshot()
        payload = canonical_json(snapshot)
        graph_hash = canonical_sha256(snapshot)
        with self._transaction() as connection:
            self._require_revision(connection, case_id, expected_revision)
            try:
                connection.execute(
                    """
                    INSERT INTO claim_graphs(case_id, revision, payload_json, payload_hash)
                    VALUES (?, ?, ?, ?)
                    """,
                    (case_id, expected_revision, payload, graph_hash),
                )
                changed = connection.execute(
                    """
                    UPDATE cases SET graph_revision = ?, graph_hash = ?
                    WHERE case_id = ? AND revision = ?
                    """,
                    (expected_revision, graph_hash, case_id, expected_revision),
                ).rowcount
                if changed != 1:
                    raise RevisionConflictError("case revision changed while anchoring graph")
            except sqlite3.IntegrityError as error:
                raise ValueError("claim graph records are immutable") from error

    def list_evidence_bundles(self, case_id: str) -> tuple[EvidenceBundle, ...]:
        with self._connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM cases WHERE case_id = ?", (case_id,)
            ).fetchone()
            if exists is None:
                raise ValueError("unknown case identifier")
            rows = connection.execute(
                """
                SELECT bundle_json FROM evidence_bundles
                WHERE case_id = ? ORDER BY bundle_sequence
                """,
                (case_id,),
            ).fetchall()
            bundles = tuple(_decode_model(EvidenceBundle, str(row[0])) for row in rows)
        self._verify_bundle_chain(case_id)
        return bundles

    def find_export(self, case_id: str, export_id: str) -> ExportRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT export_id, revision, parent_manifest_hash, manifest_json, manifest_hash
                FROM exports WHERE case_id = ? AND export_id = ?
                """,
                (case_id, export_id),
            ).fetchone()
            return None if row is None else self._export_record(connection, case_id, row)

    def latest_export(self, case_id: str) -> ExportRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT export_id, revision, parent_manifest_hash, manifest_json, manifest_hash
                FROM exports WHERE case_id = ?
                ORDER BY revision DESC, export_id DESC LIMIT 1
                """,
                (case_id,),
            ).fetchone()
            return None if row is None else self._export_record(connection, case_id, row)

    def record_export(
        self,
        case_id: str,
        record: ExportRecord,
        *,
        expected_revision: int,
        created_at: datetime,
    ) -> None:
        if record.revision != expected_revision:
            raise ValueError("export record revision does not match its case revision")
        if canonical_sha256(safe_parse_json(record.manifest_json)) != record.manifest_hash:
            raise ValueError("export manifest hash mismatch")
        if list(record.artifact_hashes) != sorted(record.artifact_hashes):
            raise ValueError("export artifact lineage must be deterministically ordered")
        with self._transaction() as connection:
            self._require_revision(connection, case_id, expected_revision)
            existing_row = connection.execute(
                """
                SELECT export_id, revision, parent_manifest_hash, manifest_json, manifest_hash
                FROM exports WHERE case_id = ? AND export_id = ?
                """,
                (case_id, record.export_id),
            ).fetchone()
            if existing_row is not None:
                if self._export_record(connection, case_id, existing_row) != record:
                    raise ValueError("immutable export identifier already has different content")
                return
            parent_row = connection.execute(
                """
                SELECT manifest_hash FROM exports WHERE case_id = ?
                ORDER BY revision DESC, export_id DESC LIMIT 1
                """,
                (case_id,),
            ).fetchone()
            expected_parent = "0" * 64 if parent_row is None else str(parent_row[0])
            if record.parent_manifest_hash != expected_parent:
                raise ValueError("export does not extend the durable export lineage")
            try:
                connection.execute(
                    """
                    INSERT INTO exports(
                        case_id, export_id, revision, parent_manifest_hash,
                        manifest_json, manifest_hash, created_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        case_id,
                        record.export_id,
                        record.revision,
                        record.parent_manifest_hash,
                        record.manifest_json,
                        record.manifest_hash,
                        _utc_text(created_at),
                    ),
                )
                for artifact_path, artifact_hash in record.artifact_hashes:
                    connection.execute(
                        """
                        INSERT INTO export_artifacts(
                            case_id, export_id, artifact_path, artifact_hash
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (case_id, record.export_id, artifact_path, artifact_hash),
                    )
            except sqlite3.IntegrityError as error:
                raise ValueError("duplicate or inconsistent export lineage rejected") from error

    def reconstruct(self, case_id: str, *, require_complete: bool = False) -> DurableCase:
        return self._reconstruct(
            case_id,
            require_complete=require_complete,
            allow_pending_final_graph=False,
        )

    def _reconstruct(
        self,
        case_id: str,
        *,
        require_complete: bool,
        allow_pending_final_graph: bool,
    ) -> DurableCase:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT schema_version, revision, state, created_at_utc, updated_at_utc,
                       semantic_hash, audit_head_hash, finalized, graph_revision, graph_hash
                FROM cases WHERE case_id = ?
                """,
                (case_id,),
            ).fetchone()
            if row is None:
                raise ValueError("unknown case identifier")
            events = self._load_events(connection, case_id)
            audit = AuditLog(events)
            case = audit.replay_case(require_complete=require_complete)
            expected_created = _utc_text(events[0].timestamp)
            expected_updated = _utc_text(events[-1].timestamp)
            if str(row[0]) != case.schema_version:
                raise ValueError("durable case schema version mismatch")
            if int(row[1]) != len(events):
                raise ValueError("case revision does not match its event inventory")
            if str(row[2]) != case.state.value:
                raise ValueError("durable workflow state mismatch")
            if str(row[3]) != expected_created or str(row[4]) != expected_updated:
                raise ValueError("durable case timestamps do not match audited events")
            if str(row[5]) != canonical_sha256(case):
                raise ValueError("durable case semantic hash mismatch")
            if str(row[6]) != events[-1].current_event_hash:
                raise ValueError("durable case audit head mismatch")
            if bool(row[7]) != (case.state is WorkflowState.CHAIR_EXPLANATION):
                raise ValueError("durable case finalization state mismatch")
            graph_revision = None if row[8] is None else int(row[8])
            graph_hash = None if row[9] is None else str(row[9])
            if (graph_revision is None) != (graph_hash is None):
                raise ValueError("durable claim-graph anchor is partial")
            if graph_revision is not None and graph_revision > len(events):
                raise ValueError("durable claim-graph revision exceeds the case revision")
            if (
                case.state is WorkflowState.CHAIR_EXPLANATION
                and graph_revision != len(events)
                and not allow_pending_final_graph
            ):
                raise ValueError("finalized cases require a graph anchored at the final revision")
            ledger = self._reconstruct_ledger(case, events)
            graph = self._load_graph(
                connection,
                case_id,
                ledger,
                expected_revision=graph_revision,
                expected_hash=graph_hash,
                required=(
                    case.state is WorkflowState.CHAIR_EXPLANATION and not allow_pending_final_graph
                ),
            )
            self._verify_materializations(connection, case, events, ledger)
            self._verify_provider_invocations(connection, case_id, events)
            durable = DurableCase(
                case=case,
                audit_log=audit,
                revision=len(events),
                semantic_hash=str(row[5]),
                audit_head_hash=str(row[6]),
                graph_revision=graph_revision,
                graph_hash=graph_hash,
                evidence_ledger=ledger,
                claim_graph=graph,
            )
        self._verify_bundle_chain(case_id)
        return durable

    def verify(self) -> StoreInspection:
        with self._connection() as connection:
            result = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            if result != "ok":
                raise ValueError("SQLite integrity check failed")
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ValueError("SQLite foreign-key integrity check failed")
            case_ids = [
                str(row[0])
                for row in connection.execute("SELECT case_id FROM cases ORDER BY case_id")
            ]
        if len(case_ids) > MAX_CASES:
            raise ValueError("case-store case limit exceeded")
        for case_id in case_ids:
            self.reconstruct(case_id, require_complete=False)
            self._verify_bundle_chain(case_id)
            self._verify_export_chain(case_id)
        return self.inspect()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._open_raw(create=False)
        identity = self._file_identity()
        try:
            self._validate_schema(connection)
            yield connection
            self._assert_file_identity(identity)
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._open_raw(create=False)
        identity = self._file_identity()
        try:
            self._validate_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            self._assert_file_identity(identity)
            connection.execute("COMMIT")
        except BaseException:
            with suppress(sqlite3.Error):
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def _open_raw(self, *, create: bool) -> sqlite3.Connection:
        reject_symlink_components(self._path)
        self._validate_sidecars()
        if not create:
            if self._path.is_symlink() or not self._path.is_file():
                raise ValueError("case store must be a regular non-symlink file")
            if self._path.stat().st_size > MAX_DATABASE_BYTES:
                raise ValueError("case-store database exceeds its resource limit")
        identity_before = self._file_identity() if self._path.exists() else None
        connection = sqlite3.connect(
            self._path,
            timeout=self._busy_timeout_ms / 1000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        self._configure_connection(connection)
        journal_mode = str(connection.execute("PRAGMA journal_mode=WAL").fetchone()[0])
        if journal_mode.casefold() != "wal":
            connection.close()
            raise ValueError("case store requires SQLite WAL journaling")
        identity_after = self._file_identity()
        if identity_before is not None and identity_before != identity_after:
            connection.close()
            raise ValueError("case-store database was replaced while opening")
        return connection

    def _configure_connection(self, connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA recursive_triggers=OFF")
        connection.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
        connection.execute("PRAGMA synchronous=FULL")
        if hasattr(connection, "setlimit"):
            connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_CANONICAL_PAYLOAD_BYTES + 65_536)
            connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 200_000)
            connection.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 256)
            connection.setlimit(sqlite3.SQLITE_LIMIT_COMPOUND_SELECT, 32)
            connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 128)

    def _apply_migrations(self, connection: sqlite3.Connection, target: int) -> None:
        current = int(connection.execute("PRAGMA user_version").fetchone()[0])
        objects = _schema_objects(connection)
        if current == 0 and objects:
            raise ValueError("unversioned nonempty databases are not QuantForge stores")
        if current > LATEST_SCHEMA_VERSION:
            raise ValueError("case store uses an unknown future schema version")
        for migration in MIGRATIONS:
            if migration.version <= current or migration.version > target:
                continue
            applied_at = _now_utc_text()
            try:
                connection.execute("BEGIN EXCLUSIVE")
                for statement in migration.statements:
                    connection.execute(statement)
                if migration.version == 1:
                    identity_payload = {"at": applied_at, "path": self._path.name}
                    store_id = f"store_{canonical_sha256(identity_payload)[:32]}"
                    connection.execute(
                        """
                        INSERT INTO store_metadata(
                            singleton, store_id, schema_version, created_at_utc, updated_at_utc
                        ) VALUES (1, ?, 1, ?, ?)
                        """,
                        (store_id, applied_at, applied_at),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE store_metadata SET schema_version = ?, updated_at_utc = ?
                        WHERE singleton = 1 AND schema_version = ?
                        """,
                        (migration.version, applied_at, migration.version - 1),
                    )
                connection.execute(
                    """
                    INSERT INTO migration_history(version, name, checksum, applied_at_utc)
                    VALUES (?, ?, ?, ?)
                    """,
                    (migration.version, migration.name, migration.checksum, applied_at),
                )
                connection.execute(f"PRAGMA user_version={migration.version}")
                connection.execute("COMMIT")
            except BaseException:
                with suppress(sqlite3.Error):
                    connection.execute("ROLLBACK")
                raise
            current = migration.version

    def _validate_schema(
        self, connection: sqlite3.Connection, *, allow_historical: bool = False
    ) -> int:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version < 1:
            object_count = int(
                connection.execute(
                    "SELECT count(*) FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'"
                ).fetchone()[0]
            )
            if object_count:
                raise ValueError("unversioned database is not a QuantForge case store")
            raise ValueError("database is not an initialized QuantForge store")
        if version > LATEST_SCHEMA_VERSION:
            raise ValueError("case store uses an unknown future schema version")
        if not allow_historical and version != LATEST_SCHEMA_VERSION:
            raise ValueError("case store requires a forward migration")
        application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
        if application_id != APPLICATION_ID:
            raise ValueError("database application identity is not QuantForge")
        journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).casefold()
        if journal_mode not in {"wal", "memory"}:
            raise ValueError("case store is not using its crash-safe journal mode")
        metadata = connection.execute(
            "SELECT schema_version FROM store_metadata WHERE singleton = 1"
        ).fetchone()
        if metadata is None or int(metadata[0]) != version:
            raise ValueError("partial or inconsistent schema migration detected")
        history = connection.execute(
            "SELECT version, name, checksum FROM migration_history ORDER BY version"
        ).fetchall()
        if len(history) != version:
            raise ValueError("migration history is incomplete")
        for row, migration in zip(history, MIGRATIONS[:version], strict=True):
            if (int(row[0]), str(row[1]), str(row[2])) != (
                migration.version,
                migration.name,
                migration.checksum,
            ):
                raise ValueError("migration history checksum mismatch")
        objects = _schema_objects(connection)
        tables = {name for kind, name, _, _ in objects if kind == "table"}
        if tables != _EXPECTED_TABLES[version] or any(
            kind not in {"table", "index"} for kind, _, _, _ in objects
        ):
            raise ValueError("database contains missing or unauthorized schema objects")
        if canonical_sha256(objects) != _SCHEMA_FINGERPRINTS[version]:
            raise ValueError("database schema fingerprint mismatch")
        return version

    def _inspection(self, connection: sqlite3.Connection, *, integrity: str) -> StoreInspection:
        version = self._validate_schema(connection, allow_historical=True)
        exports = (
            int(connection.execute("SELECT count(*) FROM exports").fetchone()[0])
            if version >= 2
            else 0
        )
        provider_invocations = (
            int(connection.execute("SELECT count(*) FROM provider_invocations").fetchone()[0])
            if version >= 4
            else 0
        )
        return StoreInspection(
            backend="sqlite",
            schema_version=version,
            case_count=int(connection.execute("SELECT count(*) FROM cases").fetchone()[0]),
            event_count=int(connection.execute("SELECT count(*) FROM audit_events").fetchone()[0]),
            bundle_count=int(
                connection.execute("SELECT count(*) FROM evidence_bundles").fetchone()[0]
            ),
            export_count=exports,
            integrity=integrity,
            provider_invocation_count=provider_invocations,
        )

    def _append_event_transaction(
        self,
        connection: sqlite3.Connection,
        event: AuditEvent,
        expected_revision: int,
    ) -> int:
        row = connection.execute(
            "SELECT revision, finalized FROM cases WHERE case_id = ?", (event.case_id,)
        ).fetchone()
        if row is None:
            raise ValueError("unknown case identifier")
        revision = int(row[0])
        if revision != expected_revision:
            raise RevisionConflictError(
                f"revision conflict: expected {expected_revision}, found {revision}"
            )
        if bool(row[1]):
            raise ValueError("finalized cases cannot accept additional workflow events")
        if revision >= MAX_EVENTS_PER_CASE or event.sequence != revision + 1:
            raise ValueError("audit sequence is not the next bounded case revision")
        events = self._load_events(connection, event.case_id)
        audit = AuditLog((*events, event))
        case = audit.replay_case(require_complete=False)
        try:
            self._insert_event(connection, event)
            self._materialize_event(connection, case, event)
            changed = connection.execute(
                """
                UPDATE cases
                SET revision = ?, state = ?, updated_at_utc = ?, semantic_hash = ?,
                    audit_head_hash = ?, finalized = ?
                WHERE case_id = ? AND revision = ?
                """,
                (
                    event.sequence,
                    case.state.value,
                    _utc_text(event.timestamp),
                    canonical_sha256(case),
                    event.current_event_hash,
                    int(case.state is WorkflowState.CHAIR_EXPLANATION),
                    case.case_id,
                    expected_revision,
                ),
            ).rowcount
        except sqlite3.IntegrityError as error:
            raise ValueError(
                "immutable durable record already exists or is inconsistent"
            ) from error
        if changed != 1:
            raise RevisionConflictError("case revision changed during append")
        return event.sequence

    def _insert_provider_invocation(
        self,
        connection: sqlite3.Connection,
        record: ProviderInvocationRecord,
    ) -> None:
        record_json = canonical_json(record)
        if len(record_json.encode("utf-8")) > MAX_CANONICAL_PAYLOAD_BYTES:
            raise ValueError("provider invocation exceeds the durable resource limit")
        record_hash = canonical_sha256(record)
        existing = connection.execute(
            """
            SELECT record_json, record_hash FROM provider_invocations
            WHERE case_id = ? AND invocation_id = ?
            """,
            (record.case_id, record.invocation_id),
        ).fetchone()
        if existing is not None:
            if str(existing[0]) == record_json and str(existing[1]) == record_hash:
                return
            raise ValueError("immutable provider invocation identifier was substituted")
        try:
            connection.execute(
                """
                INSERT INTO provider_invocations(
                    case_id, invocation_id, case_revision, reviewer_role, role_action,
                    request_semantic_hash, status, record_json, record_hash, recorded_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.case_id,
                    record.invocation_id,
                    record.case_revision,
                    record.role.value,
                    record.action.value,
                    record.request_semantic_sha256,
                    record.status.value,
                    record_json,
                    record_hash,
                    _utc_text(record.recorded_at),
                ),
            )
            for attempt in record.attempts:
                connection.execute(
                    """
                    INSERT INTO provider_attempts(
                        case_id, invocation_id, attempt_index,
                        observation_json, observation_hash
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        record.case_id,
                        record.invocation_id,
                        attempt.attempt_index,
                        canonical_json(attempt),
                        canonical_sha256(attempt),
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(
                "provider retries cannot create duplicate durable reviewer votes"
            ) from error

    @staticmethod
    def _anchor_final_graph_transaction(
        connection: sqlite3.Connection,
        case_id: str,
        revision: int,
        snapshot: ClaimGraphSnapshot,
        graph_hash: str,
    ) -> None:
        existing = int(
            connection.execute(
                "SELECT count(*) FROM claim_graphs WHERE case_id = ?", (case_id,)
            ).fetchone()[0]
        )
        if existing:
            raise ValueError("final provider transaction requires an unanchored claim graph")
        try:
            connection.execute(
                """
                INSERT INTO claim_graphs(case_id, revision, payload_json, payload_hash)
                VALUES (?, ?, ?, ?)
                """,
                (case_id, revision, canonical_json(snapshot), graph_hash),
            )
            changed = connection.execute(
                """
                UPDATE cases SET graph_revision = ?, graph_hash = ?
                WHERE case_id = ? AND revision = ?
                      AND graph_revision IS NULL AND graph_hash IS NULL
                """,
                (revision, graph_hash, case_id, revision),
            ).rowcount
        except sqlite3.IntegrityError as error:
            raise ValueError("final claim graph is not an immutable unique anchor") from error
        if changed != 1:
            raise RevisionConflictError("case changed while anchoring its final claim graph")

    @staticmethod
    def _decode_provider_invocation(row: sqlite3.Row) -> ProviderInvocationRecord:
        record = _decode_model(ProviderInvocationRecord, str(row[7]))
        columns = (
            str(row[0]),
            str(row[1]),
            int(row[2]),
            str(row[3]),
            str(row[4]),
            str(row[5]),
            str(row[6]),
            str(row[9]),
        )
        expected = (
            record.case_id,
            record.invocation_id,
            record.case_revision,
            record.role.value,
            record.action.value,
            record.request_semantic_sha256,
            record.status.value,
            _utc_text(record.recorded_at),
        )
        if (
            columns != expected
            or canonical_sha256(record) != str(row[8])
            or canonical_json(record) != str(row[7])
        ):
            raise ValueError("durable provider invocation hash mismatch")
        return record

    @staticmethod
    def _verify_provider_attempt_rows(
        connection: sqlite3.Connection,
        record: ProviderInvocationRecord,
    ) -> None:
        rows = connection.execute(
            """
            SELECT attempt_index, observation_json, observation_hash
            FROM provider_attempts WHERE case_id = ? AND invocation_id = ?
            ORDER BY attempt_index
            """,
            (record.case_id, record.invocation_id),
        ).fetchall()
        actual = [(int(row[0]), str(row[1]), str(row[2])) for row in rows]
        expected = [
            (attempt.attempt_index, canonical_json(attempt), canonical_sha256(attempt))
            for attempt in record.attempts
        ]
        if actual != expected:
            raise ValueError("durable provider attempt inventory mismatch")

    def _insert_bundle(
        self,
        connection: sqlite3.Connection,
        bundle: EvidenceBundle,
        bundle_sequence: int,
    ) -> None:
        signature = canonical_json(bundle.signature) if bundle.signature is not None else None
        try:
            connection.execute(
                """
                INSERT INTO evidence_bundles(
                    case_id, bundle_sequence, bundle_id, workflow_revision,
                    bundle_json, bundle_hash, previous_bundle_hash, observed_at_utc,
                    signature_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bundle.semantic.case_id,
                    bundle_sequence,
                    bundle.semantic.bundle_id,
                    bundle.semantic.workflow_revision,
                    canonical_json(bundle),
                    bundle.bundle_hash,
                    bundle.semantic.previous_bundle_hash,
                    _utc_text(bundle.observations.admitted_at),
                    signature,
                ),
            )
            semantics = {item.path: item for item in bundle.semantic.input_artifacts}
            semantics.update({item.path: item for item in bundle.semantic.output_artifacts})
            for direction, inventory in (
                ("input", bundle.observations.input_artifacts),
                ("output", bundle.observations.output_artifacts),
            ):
                for artifact in inventory:
                    semantic = semantics[artifact.path]
                    connection.execute(
                        """
                        INSERT INTO bundle_artifacts(
                            case_id, bundle_id, direction, artifact_path, byte_sha256,
                            semantic_sha256, size_bytes, schema_version
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            bundle.semantic.case_id,
                            bundle.semantic.bundle_id,
                            direction,
                            artifact.path,
                            artifact.byte_sha256,
                            semantic.semantic_sha256,
                            artifact.size_bytes,
                            semantic.schema_version,
                        ),
                    )
        except sqlite3.IntegrityError as error:
            raise ValueError("duplicate or substituted evidence bundle rejected") from error

    def _insert_event(self, connection: sqlite3.Connection, event: AuditEvent) -> None:
        payload_json = canonical_json(event.payload)
        if len(payload_json.encode("utf-8")) > MAX_CANONICAL_PAYLOAD_BYTES:
            raise ValueError("audit payload exceeds the durable resource limit")
        connection.execute(
            """
            INSERT INTO audit_events(
                case_id, sequence, event_id, timestamp_utc, workflow_state, actor, action,
                payload_json, payload_hash, previous_event_hash, current_event_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.case_id,
                event.sequence,
                event.event_id,
                _utc_text(event.timestamp),
                event.workflow_state.value,
                event.actor.value,
                event.action,
                payload_json,
                event.payload_hash,
                event.previous_event_hash,
                event.current_event_hash,
            ),
        )

    def _load_events(self, connection: sqlite3.Connection, case_id: str) -> tuple[AuditEvent, ...]:
        rows = connection.execute(
            """
            SELECT sequence, event_id, timestamp_utc, workflow_state, actor, action,
                   payload_json, payload_hash, previous_event_hash, current_event_hash
            FROM audit_events WHERE case_id = ? ORDER BY sequence
            LIMIT ?
            """,
            (case_id, MAX_EVENTS_PER_CASE + 1),
        ).fetchall()
        if len(rows) > MAX_EVENTS_PER_CASE:
            raise ValueError("case audit event limit exceeded")
        events: list[AuditEvent] = []
        for row in rows:
            value: dict[str, Any] = {
                "event_id": str(row[1]),
                "schema_version": "1.0",
                "sequence": int(row[0]),
                "timestamp": str(row[2]),
                "case_id": case_id,
                "workflow_state": str(row[3]),
                "actor": str(row[4]),
                "action": str(row[5]),
                "payload": safe_parse_json(str(row[6]), max_bytes=MAX_CANONICAL_PAYLOAD_BYTES),
                "payload_hash": str(row[7]),
                "previous_event_hash": str(row[8]),
                "current_event_hash": str(row[9]),
            }
            events.append(AuditEvent.model_validate_json(canonical_json(value)))
        if not events:
            raise ValueError("durable case has no audit events")
        return tuple(events)

    def _materialize_event(
        self, connection: sqlite3.Connection, case: TribunalCase, event: AuditEvent
    ) -> None:
        payload = canonical_json(event.payload)
        payload_hash = canonical_sha256(event.payload)
        if event.workflow_state is WorkflowState.CONSTITUTION_LOCKED:
            constitution = _decode_model(ExperimentConstitution, payload)
            connection.execute(
                """
                INSERT INTO constitutions(
                    case_id, constitution_id, revision, payload_json, payload_hash
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    case.case_id,
                    constitution.constitution_id,
                    event.sequence,
                    payload,
                    payload_hash,
                ),
            )
        elif event.workflow_state is WorkflowState.EXPERIMENT_EXECUTED:
            snapshot = _decode_model(EvidenceLedgerSnapshot, payload)
            for evidence in snapshot.evidence:
                bundle_value = evidence.provenance.get("bundle_id")
                bundle_id = bundle_value if isinstance(bundle_value, str) else None
                if evidence.source_adapter == "cpp_v1_adapter" and bundle_id is None:
                    raise ValueError("engine evidence lacks its durable bundle identifier")
                connection.execute(
                    """
                    INSERT INTO evidence_records(
                        case_id, evidence_id, bundle_id, revision, payload_json, payload_hash
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        case.case_id,
                        evidence.evidence_id,
                        bundle_id,
                        event.sequence,
                        canonical_json(evidence),
                        canonical_sha256(evidence),
                    ),
                )
        elif event.workflow_state in {
            WorkflowState.METHODOLOGY_REVIEWED,
            WorkflowState.STATISTICS_REVIEWED,
            WorkflowState.ADVERSARIAL_REVIEWED,
            WorkflowState.REPRODUCIBILITY_VERIFIED,
            WorkflowState.CHAIR_EXPLANATION,
        }:
            review_id = event.payload.get("review_id") if isinstance(event.payload, dict) else None
            if review_id is None and isinstance(event.payload, dict):
                nested = event.payload.get("reproducibility_review")
                review_id = nested.get("review_id") if isinstance(nested, dict) else None
                if nested is not None:
                    payload = canonical_json(nested)
                    payload_hash = canonical_sha256(nested)
            if event.workflow_state is WorkflowState.CHAIR_EXPLANATION:
                review_id = (
                    event.payload.get("explanation_id") if isinstance(event.payload, dict) else None
                )
            if not isinstance(review_id, str):
                raise ValueError("review materialization lacks an immutable identifier")
            connection.execute(
                """
                INSERT INTO reviewer_outputs(
                    case_id, review_id, reviewer_role, revision, payload_json, payload_hash
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (case.case_id, review_id, event.actor.value, event.sequence, payload, payload_hash),
            )
        elif event.workflow_state is WorkflowState.VERDICT_ELIGIBILITY_COMPUTED:
            if not isinstance(event.payload, dict):
                raise ValueError("verdict materialization payload must be an object")
            eligibility = event.payload.get("eligibility")
            if not isinstance(eligibility, dict) or not isinstance(
                eligibility.get("eligibility_id"), str
            ):
                raise ValueError("verdict materialization lacks an eligibility identifier")
            connection.execute(
                """
                INSERT INTO verdict_results(
                    case_id, eligibility_id, revision, payload_json, payload_hash
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    case.case_id,
                    eligibility["eligibility_id"],
                    event.sequence,
                    canonical_json(eligibility),
                    canonical_sha256(eligibility),
                ),
            )

    def _reconstruct_ledger(
        self, case: TribunalCase, events: tuple[AuditEvent, ...]
    ) -> EvidenceLedger | None:
        executed = [
            event for event in events if event.workflow_state is WorkflowState.EXPERIMENT_EXECUTED
        ]
        if not executed:
            return None
        if len(executed) != 1:
            raise ValueError("case contains multiple primary experiment evidence snapshots")
        snapshot = EvidenceLedgerSnapshot.model_validate_json(canonical_json(executed[0].payload))
        return EvidenceLedger.from_snapshot(snapshot, claim_ids={case.claim.claim_id})

    def _load_graph(
        self,
        connection: sqlite3.Connection,
        case_id: str,
        ledger: EvidenceLedger | None,
        *,
        expected_revision: int | None,
        expected_hash: str | None,
        required: bool,
    ) -> ClaimGraph | None:
        rows = connection.execute(
            """
            SELECT revision, payload_json, payload_hash FROM claim_graphs
            WHERE case_id = ? ORDER BY revision
            """,
            (case_id,),
        ).fetchall()
        if not rows:
            if required or expected_revision is not None or expected_hash is not None:
                raise ValueError("required durable claim graph is missing")
            return None
        if len(rows) != 1:
            raise ValueError("claim graph contains unanchored historical materializations")
        if expected_revision is None or expected_hash is None:
            raise ValueError("durable claim graph exists without a case anchor")
        previous_revision = 0
        snapshots: list[ClaimGraphSnapshot] = []
        for row in rows:
            revision = int(row[0])
            if revision <= previous_revision:
                raise ValueError("claim graph revisions are not append-only")
            snapshot = _decode_model(ClaimGraphSnapshot, str(row[1]))
            if canonical_sha256(snapshot) != str(row[2]):
                raise ValueError("claim graph payload hash mismatch")
            snapshots.append(snapshot)
            previous_revision = revision
        if previous_revision != expected_revision or str(rows[-1][2]) != expected_hash:
            raise ValueError("claim graph does not match its case revision anchor")
        snapshot = snapshots[-1]
        graph = ClaimGraph.from_snapshot(snapshot)
        if ledger is None:
            raise ValueError("claim graph exists without a durable evidence ledger")
        graph.validate_against_ledger(ledger)
        graph.validate_final_claim_traceability()
        return graph

    def _verify_materializations(
        self,
        connection: sqlite3.Connection,
        case: TribunalCase,
        events: tuple[AuditEvent, ...],
        ledger: EvidenceLedger | None,
    ) -> None:
        constitution_rows = connection.execute(
            """
            SELECT case_id, constitution_id, revision, payload_json, payload_hash
            FROM constitutions WHERE case_id = ? ORDER BY constitution_id
            """,
            (case.case_id,),
        ).fetchall()
        constitution_event = next(
            (
                event
                for event in events
                if event.workflow_state is WorkflowState.CONSTITUTION_LOCKED
            ),
            None,
        )
        expected_constitutions: list[tuple[str, str, int, str, str]] = []
        if case.constitution is not None:
            if constitution_event is None:
                raise ValueError("case constitution lacks an authoritative event")
            expected_constitutions.append(
                (
                    case.case_id,
                    case.constitution.constitution_id,
                    constitution_event.sequence,
                    canonical_json(case.constitution),
                    canonical_sha256(case.constitution),
                )
            )
        actual_constitutions = [
            (str(row[0]), str(row[1]), int(row[2]), str(row[3]), str(row[4]))
            for row in constitution_rows
        ]
        if actual_constitutions != expected_constitutions:
            raise ValueError("durable constitution materialization mismatch")
        evidence_rows = connection.execute(
            """
            SELECT case_id, evidence_id, bundle_id, revision, payload_json, payload_hash
            FROM evidence_records
            WHERE case_id = ? ORDER BY evidence_id
            """,
            (case.case_id,),
        ).fetchall()
        expected = (
            {}
            if ledger is None
            else {item.evidence_id: item for item in ledger.snapshot().evidence}
        )
        execution_event = next(
            (
                event
                for event in events
                if event.workflow_state is WorkflowState.EXPERIMENT_EXECUTED
            ),
            None,
        )
        actual: dict[str, EvidenceObject] = {}
        for row in evidence_rows:
            evidence = _decode_model(EvidenceObject, str(row[4]))
            expected_bundle = evidence.provenance.get("bundle_id")
            bundle_id = None if row[2] is None else str(row[2])
            if (
                str(row[0]) != case.case_id
                or str(row[1]) != evidence.evidence_id
                or int(row[3]) != (execution_event.sequence if execution_event else -1)
                or str(row[4]) != canonical_json(evidence)
                or canonical_sha256(evidence) != str(row[5])
                or bundle_id != (expected_bundle if isinstance(expected_bundle, str) else None)
            ):
                raise ValueError("durable evidence materialization hash mismatch")
            actual[evidence.evidence_id] = evidence
        if actual != expected:
            raise ValueError("durable evidence materialization inventory mismatch")
        bundle_rows = {
            str(row[0]): (str(row[1]), str(row[2]))
            for row in connection.execute(
                """
                SELECT bundle_id, bundle_hash, bundle_json FROM evidence_bundles
                WHERE case_id = ?
                """,
                (case.case_id,),
            )
        }
        for evidence in actual.values():
            if evidence.source_adapter != "cpp_v1_adapter":
                continue
            provenance_bundle_id = evidence.provenance.get("bundle_id")
            bundle_hash = evidence.provenance.get("bundle_hash")
            if not isinstance(provenance_bundle_id, str) or provenance_bundle_id not in bundle_rows:
                raise ValueError("engine evidence lacks its durable evidence bundle")
            durable_hash, bundle_json = bundle_rows[provenance_bundle_id]
            bundle = _decode_model(EvidenceBundle, bundle_json)
            if (
                bundle.bundle_hash != durable_hash
                or bundle_hash != durable_hash
                or evidence.content.get("bundle_hash") != durable_hash
                or evidence.content.get("semantic_hash") != bundle.semantic_hash
                or evidence.source_artifact
                not in {item.path for item in bundle.semantic.output_artifacts}
                or evidence.source_artifact_sha256
                != {
                    item.path: item.byte_sha256 for item in bundle.observations.output_artifacts
                }.get(evidence.source_artifact)
            ):
                raise ValueError("engine evidence and durable bundle provenance mismatch")
        expected_reviews: list[tuple[str, str, str, int, str, str]] = []
        for event in events:
            if event.workflow_state not in {
                WorkflowState.METHODOLOGY_REVIEWED,
                WorkflowState.STATISTICS_REVIEWED,
                WorkflowState.ADVERSARIAL_REVIEWED,
                WorkflowState.REPRODUCIBILITY_VERIFIED,
                WorkflowState.CHAIR_EXPLANATION,
            }:
                continue
            value = event.payload
            if event.workflow_state is WorkflowState.REPRODUCIBILITY_VERIFIED:
                if not isinstance(value, dict):
                    raise ValueError("reproducibility event payload is not an object")
                value = value.get("reproducibility_review")
            if not isinstance(value, dict):
                raise ValueError("review event payload is not an object")
            identity_key = (
                "explanation_id"
                if event.workflow_state is WorkflowState.CHAIR_EXPLANATION
                else "review_id"
            )
            review_id = value.get(identity_key)
            if not isinstance(review_id, str):
                raise ValueError("review event lacks its immutable identifier")
            expected_reviews.append(
                (
                    case.case_id,
                    review_id,
                    event.actor.value,
                    event.sequence,
                    canonical_json(value),
                    canonical_sha256(value),
                )
            )
        review_rows = connection.execute(
            """
            SELECT case_id, review_id, reviewer_role, revision, payload_json, payload_hash
            FROM reviewer_outputs WHERE case_id = ? ORDER BY revision, review_id
            """,
            (case.case_id,),
        ).fetchall()
        actual_reviews = [
            (
                str(row[0]),
                str(row[1]),
                str(row[2]),
                int(row[3]),
                str(row[4]),
                str(row[5]),
            )
            for row in review_rows
        ]
        if actual_reviews != expected_reviews:
            raise ValueError("durable reviewer materialization mismatch")
        verdict_events = [
            event
            for event in events
            if event.workflow_state is WorkflowState.VERDICT_ELIGIBILITY_COMPUTED
        ]
        verdict_rows = connection.execute(
            """
            SELECT case_id, eligibility_id, revision, payload_json, payload_hash
            FROM verdict_results WHERE case_id = ?
            """,
            (case.case_id,),
        ).fetchall()
        expected_verdicts: list[tuple[str, str, int, str, str]] = []
        if verdict_events:
            if len(verdict_events) != 1 or not isinstance(verdict_events[0].payload, dict):
                raise ValueError("authoritative verdict event inventory is invalid")
            eligibility = verdict_events[0].payload.get("eligibility")
            if not isinstance(eligibility, dict) or not isinstance(
                eligibility.get("eligibility_id"), str
            ):
                raise ValueError("authoritative verdict event lacks eligibility")
            eligibility_id = eligibility["eligibility_id"]
            if not isinstance(eligibility_id, str):
                raise ValueError("authoritative verdict identity is not text")
            expected_verdicts.append(
                (
                    case.case_id,
                    eligibility_id,
                    verdict_events[0].sequence,
                    canonical_json(eligibility),
                    canonical_sha256(eligibility),
                )
            )
        actual_verdicts = [
            (str(row[0]), str(row[1]), int(row[2]), str(row[3]), str(row[4]))
            for row in verdict_rows
        ]
        if actual_verdicts != expected_verdicts:
            raise ValueError("durable verdict materialization mismatch")

    def _verify_provider_invocations(
        self,
        connection: sqlite3.Connection,
        case_id: str,
        events: tuple[AuditEvent, ...],
    ) -> None:
        rows = connection.execute(
            """
            SELECT case_id, invocation_id, case_revision, reviewer_role, role_action,
                   request_semantic_hash, status, record_json, record_hash, recorded_at_utc
            FROM provider_invocations
            WHERE case_id = ? ORDER BY recorded_at_utc, invocation_id
            """,
            (case_id,),
        ).fetchall()
        expected_states = {
            RoleAction.PROPOSE_PROTOCOL: WorkflowState.RESEARCHER_PROTOCOL_PROPOSED,
            RoleAction.REVIEW_METHODOLOGY: WorkflowState.METHODOLOGY_REVIEWED,
            RoleAction.REVIEW_STATISTICS: WorkflowState.STATISTICS_REVIEWED,
            RoleAction.REQUEST_CHALLENGE: WorkflowState.ADVERSARIAL_REVIEWED,
            RoleAction.REVIEW_REPRODUCIBILITY: WorkflowState.REPRODUCIBILITY_VERIFIED,
            RoleAction.EXPLAIN_VERDICT: WorkflowState.CHAIR_EXPLANATION,
        }
        for row in rows:
            record = self._decode_provider_invocation(row)
            self._verify_provider_attempt_rows(connection, record)
            if record.status is ProviderInvocationStatus.FAILED:
                continue
            if record.case_revision >= len(events):
                raise ValueError("accepted provider invocation lacks its atomic workflow event")
            event = events[record.case_revision]
            if (
                event.sequence != record.case_revision + 1
                or event.actor is not record.role
                or event.workflow_state is not expected_states[record.action]
            ):
                raise ValueError("accepted provider invocation has a mismatched workflow event")
            payload: object = event.payload
            if record.action is RoleAction.REVIEW_REPRODUCIBILITY:
                if not isinstance(payload, dict):
                    raise ValueError("provider reproducibility event payload is malformed")
                payload = payload.get("reproducibility_review")
            accepted_result = record.accepted_result
            if accepted_result is None:
                raise ValueError("accepted provider invocation lacks its durable result")
            if canonical_sha256(payload) != canonical_sha256(accepted_result.output):
                raise ValueError("provider output and atomic workflow payload differ")

    def _verify_bundle_chain(self, case_id: str) -> None:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT case_id, bundle_sequence, bundle_id, workflow_revision, bundle_json,
                       bundle_hash, previous_bundle_hash, observed_at_utc, signature_json
                FROM evidence_bundles WHERE case_id = ? ORDER BY bundle_sequence
                """,
                (case_id,),
            ).fetchall()
            previous = "0" * 64
            for sequence, row in enumerate(rows, start=1):
                if int(row[1]) != sequence or str(row[6]) != previous:
                    raise ValueError("evidence-bundle chain is reordered or truncated")
                bundle = _decode_model(EvidenceBundle, str(row[4]))
                expected_signature = (
                    canonical_json(bundle.signature) if bundle.signature is not None else None
                )
                actual_signature = None if row[8] is None else str(row[8])
                if (
                    str(row[0]) != case_id
                    or str(row[2]) != bundle.semantic.bundle_id
                    or int(row[3]) != bundle.semantic.workflow_revision
                    or str(row[4]) != canonical_json(bundle)
                    or bundle.bundle_hash != str(row[5])
                    or bundle.semantic.previous_bundle_hash != str(row[6])
                    or str(row[7]) != _utc_text(bundle.observations.admitted_at)
                    or actual_signature != expected_signature
                ):
                    raise ValueError("evidence-bundle payload hash mismatch")
                artifact_rows = connection.execute(
                    """
                    SELECT direction, artifact_path, byte_sha256, semantic_sha256,
                           size_bytes, schema_version
                    FROM bundle_artifacts
                    WHERE case_id = ? AND bundle_id = ?
                    ORDER BY direction, artifact_path
                    """,
                    (case_id, bundle.semantic.bundle_id),
                ).fetchall()
                semantics = {item.path: item for item in bundle.semantic.input_artifacts}
                semantics.update({item.path: item for item in bundle.semantic.output_artifacts})
                expected_rows = sorted(
                    (
                        direction,
                        artifact.path,
                        artifact.byte_sha256,
                        semantics[artifact.path].semantic_sha256,
                        artifact.size_bytes,
                        semantics[artifact.path].schema_version,
                    )
                    for direction, inventory in (
                        ("input", bundle.observations.input_artifacts),
                        ("output", bundle.observations.output_artifacts),
                    )
                    for artifact in inventory
                )
                actual_rows = [
                    (
                        str(item[0]),
                        str(item[1]),
                        str(item[2]),
                        str(item[3]),
                        int(item[4]),
                        str(item[5]),
                    )
                    for item in artifact_rows
                ]
                if actual_rows != expected_rows:
                    raise ValueError("evidence-bundle artifact materialization mismatch")
                previous = str(row[5])

    def _export_record(
        self,
        connection: sqlite3.Connection,
        case_id: str,
        row: sqlite3.Row,
    ) -> ExportRecord:
        artifacts = tuple(
            (str(item[0]), str(item[1]))
            for item in connection.execute(
                """
                SELECT artifact_path, artifact_hash FROM export_artifacts
                WHERE case_id = ? AND export_id = ? ORDER BY artifact_path
                """,
                (case_id, str(row[0])),
            )
        )
        record = ExportRecord(
            export_id=str(row[0]),
            revision=int(row[1]),
            parent_manifest_hash=str(row[2]),
            manifest_json=str(row[3]),
            manifest_hash=str(row[4]),
            artifact_hashes=artifacts,
        )
        value = safe_parse_json(record.manifest_json)
        if canonical_sha256(value) != record.manifest_hash:
            raise ValueError("durable export manifest hash mismatch")
        return record

    def _verify_export_chain(self, case_id: str) -> None:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT export_id, revision, parent_manifest_hash, manifest_json, manifest_hash
                FROM exports WHERE case_id = ? ORDER BY revision, export_id
                """,
                (case_id,),
            ).fetchall()
            previous = "0" * 64
            previous_revision = 0
            for row in rows:
                record = self._export_record(connection, case_id, row)
                if record.parent_manifest_hash != previous or record.revision < previous_revision:
                    raise ValueError("durable export lineage is reordered or truncated")
                previous = record.manifest_hash
                previous_revision = record.revision

    def _require_revision(
        self, connection: sqlite3.Connection, case_id: str, expected_revision: int
    ) -> None:
        row = connection.execute(
            "SELECT revision FROM cases WHERE case_id = ?", (case_id,)
        ).fetchone()
        if row is None:
            raise ValueError("unknown case identifier")
        if int(row[0]) != expected_revision:
            raise RevisionConflictError(
                f"revision conflict: expected {expected_revision}, found {int(row[0])}"
            )

    def _file_identity(self) -> tuple[int, int]:
        reject_symlink_components(self._path)
        metadata = self._path.stat()
        if not self._path.is_file() or self._path.is_symlink():
            raise ValueError("case store must remain a regular non-symlink file")
        return (int(metadata.st_dev), int(metadata.st_ino))

    def _assert_file_identity(self, expected: tuple[int, int]) -> None:
        if self._file_identity() != expected:
            raise ValueError("case-store database was replaced during operation")
        if self._path.stat().st_size > MAX_DATABASE_BYTES:
            raise ValueError("case-store database exceeds its resource limit")
        self._validate_sidecars()

    def _validate_sidecars(self) -> None:
        for suffix, maximum in (("-wal", MAX_WAL_BYTES), ("-shm", MAX_SHM_BYTES)):
            sidecar = Path(f"{self._path}{suffix}")
            if not os.path.lexists(sidecar):
                continue
            reject_symlink_components(sidecar)
            if sidecar.is_symlink() or not sidecar.is_file():
                raise ValueError("case-store sidecar must be a regular non-symlink file")
            if sidecar.stat().st_size > maximum:
                raise ValueError("case-store sidecar exceeds its resource limit")


__all__ = [
    "APPLICATION_ID",
    "LATEST_SCHEMA_VERSION",
    "MIGRATIONS",
    "RevisionConflictError",
    "SQLiteCaseStore",
]
