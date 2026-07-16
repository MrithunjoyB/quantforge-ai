# Architecture

QuantForge is a deterministic, offline research tribunal arranged as inward-facing layers:

1. `domain` owns immutable, versioned contracts and constitution factories.
2. `serialization` owns canonical JSON, SHA-256 identity, defensive parsing, and atomic files.
3. `evidence` owns the append-only ledger, typed claim graph, and bound engine bundles.
4. `audit` owns the single-case append-only hash chain and semantic state replay.
5. `verdict` owns the pure conservative eligibility policy.
6. `roles` owns provider-neutral typed interfaces and authority checks.
7. `workflow` owns the only legal sequential orchestration.
8. `storage` owns a backend-neutral case-store contract, SQLite implementation, migrations,
   reconstruction, and deterministic package export.
9. `engine` owns the narrow read-only adapter contract for the protected C++ release.
10. `adapters` contains package-owned mock roles and synthetic evidence only.
11. `cli` exposes bounded offline operations; it is not an arbitrary process or filesystem API.

## Authority boundary

QuantForge owns workflow state, human approval, constitution locking, evidence admission, reviewer
authority, audit replay, the claim graph, verdict eligibility, and Chair constraints. The protected
`MrithunjoyB/cpp-event-driven-backtester` release `v1.0.0` remains the numerical authority for
simulation, statistics, reconstruction artifacts, and engine-side validation. The adapter cannot
let the engine change tribunal state or decide that its own output is evidence.

Raw engine files are untrusted. The adapter first validates the exact release and executable,
stages a fixed public synthetic fixture into an isolated directory, executes fixed argument arrays,
runs the release validator, inventories and hashes every output, and emits a bundle. QuantForge then
checks the bundle against current durable case state in the same transaction that appends its
workflow event and evidence materialization.

## Durable and derived state

The semantic audit chain is authoritative for case reconstruction. SQLite stores that chain plus
referentially constrained materializations of the constitution, evidence, graph, reviewer outputs,
verdict result, bundle inventory, and export lineage. Reconstruction replays the events and compares
every materialization and hash; a snapshot is never trusted independently. See
[Storage Model](STORAGE_MODEL.md) and [Migration Policy](MIGRATION_POLICY.md).

SQLite is deliberately local and single-node. It provides transactions, WAL recovery, foreign keys,
bounded busy waiting, and optimistic revisions, but not distributed consensus or an external trust
anchor. A complete locally rehashed replacement remains detectable only when compared with a trusted
external digest or signed/anchored publication.

No live provider, market-data ingestion, broker, order, or trading component exists. A later
provider adapter may propose typed role output, but code-owned workflow and evidence authority must
remain unchanged.
