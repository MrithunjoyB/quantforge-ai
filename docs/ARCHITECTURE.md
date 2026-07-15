# Architecture

QuantForge Phase 1 is a deterministic domain application arranged as inward-facing layers:

1. `domain` owns immutable versioned contracts and constitution factories.
2. `serialization` owns canonical JSON, SHA-256 identity, defensive parsing, and export.
3. `evidence` owns the append-only ledger and typed claim graph.
4. `audit` owns the single-case append-only hash chain, hashed payloads, and full state replay.
5. `verdict` owns the pure conservative policy.
6. `roles` owns provider-neutral typed interfaces and authority checks.
7. `workflow` owns the only legal sequential orchestration.
8. `adapters` contains package-owned mock roles and evidence only.
9. `cli` exposes offline demos and validators.

The architecture deliberately uses an in-memory aggregate and canonical files. A database, graph
database, web framework, queue, vector store, and agent framework would add operational state without
evidence that Phase 1 needs it.

External provider output can enter only through a future adapter that returns the same validated
domain models. Workflow state, evidence integrity, and verdict policy remain code-owned even when a
language model later proposes role findings.

A case file is a deterministic snapshot, not independent proof of history. Governed restoration
requires the complete audit JSONL: replay validates every state, actor, action, payload, identity,
derived verdict input, and final snapshot. The CLI therefore requires both files for `case validate`.
