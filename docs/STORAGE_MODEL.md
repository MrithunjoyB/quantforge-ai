# Storage Model

`CaseStore` is the backend-independent contract. `SQLiteCaseStore` is the Phase 2A local backend and
uses only Python's standard `sqlite3` module. The semantic audit chain remains authoritative; tables
for constitutions, evidence, graphs, reviews, verdicts, bundles, and exports are constrained
materializations that are verified against replay.

## Schema 3

Schema 1 creates `store_metadata`, `migration_history`, `cases`, `audit_events`, `constitutions`,
`evidence_bundles`, `bundle_artifacts`, `evidence_records`, `claim_graphs`, `reviewer_outputs`, and
`verdict_results`. Schema 2 adds immutable `exports` and `export_artifacts` lineage. Schema 3 adds
the current claim-graph revision and hash anchor to each case. Tables are `STRICT`, foreign keys use
restrictive deletes, immutable identifiers are primary/unique keys, and reads always specify
deterministic ordering.

Each store records a QuantForge application ID, `user_version`, schema version, store ID, UTC
creation/update timestamps, and ordered migration history. Each case records a stable ID, optimistic
revision, workflow state, semantic hash, audit head, and finalization bit. Each event records its
sequence, actor/action/state, canonical payload and payload hash, prior/current event hashes, and UTC
timestamp. Payloads are JSON only—pickle and executable serialization are forbidden.

## Write and recovery semantics

Creation and every append execute in `BEGIN IMMEDIATE` transactions. The expected revision must
match both the selected case row and the final conditional update. Bundle admission inserts the
bundle/artifact inventory, evidence materialization, workflow event, and new case revision atomically.
Foreign keys, full synchronous WAL, bounded busy timeouts, and rollback on exceptions provide local
crash safety. Case finalization rejects all later events.

Connections apply resource limits and defensive pragmas. Database size, case/event counts, canonical
payload sizes, bundle artifact counts/sizes, and JSON/CSV parsing are bounded. Operations reject
symlink paths and compare the database device/inode before and after critical reads so path
replacement does not silently switch the reconstructed source.
Regular WAL and SHM sidecars are separately type-, symlink-, and size-bounded before and after
operations.

`verify()` runs SQLite integrity and foreign-key checks, validates the exact schema fingerprint and
migration checksums, reconstructs every case in ID order, verifies audit/bundle chains and all
materializations, and checks export records. Any discrepancy raises an error; there is no repair or
best-effort mode.

The replay contract compares exact case schema/state/revision/timestamps/finalization/semantic/audit
fields; constitution identity/revision/payload; evidence case/bundle/revision/payload; bundle and
artifact redundant columns; reviewer role/revision/payload; verdict identity/revision/payload; and
the graph payload plus final-revision anchor. Every `cpp_v1_adapter` evidence row must resolve to its
exact bundle hash and output artifact. A finalized case requires exactly one current, append-only
graph materialization anchored at its final case revision.

## Deterministic packages

An export contains canonical `case.json`, `audit.jsonl`, `evidence_bundles.json`, and—when present—
the ledger and claim graph. Its canonical manifest binds artifact digests, case semantic hash, audit
head, bundle-chain head and IDs, evidence IDs and bundle relationships, graph presence/revision/hash,
workflow revision/state, completeness, deterministic export ID, and parent manifest hash. The
verifier recomputes these derived claims from audit replay and package contents. No wall clock enters
package bytes. Output is assembled privately and atomically renamed; an existing output path is
never overwritten. If durable lineage recording fails, the newly renamed package is removed so it
cannot appear authoritative. See [Deterministic Semantics](DETERMINISM.md).
