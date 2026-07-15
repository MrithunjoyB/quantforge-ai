# Experiment Constitution

The constitution is the scientific contract that prevents results-driven protocol drift. It embeds
the complete proposal, explicit human approval, lock timestamp, schema version, stable identity, and
a SHA-256 digest of canonical JSON.

The approval records the exact proposal digest. Constitution construction rejects a negative or
mismatched approval, and validation recomputes both proposal and constitution identities. Frozen
models prevent in-process field mutation after lock.

Amendments are separate append-only objects classified as `reviewer_requested`, `exploratory`, or
`administrative`. Each records author role, timestamp, reason, changes, parent constitution hash, and
its own canonical hash. Classification controls both author roles and key namespaces:
`follow_up.*`/`robustness.*`, `exploratory.*`, or `metadata.*`. Validation rejects nested or
path-encoded attempts to rewrite primary hypotheses, null hypotheses, or failure criteria. Case
validation requires a continuous parent-hash chain. Exploratory findings remain separate from the
primary proposal; an amendment never changes the original constitution object.

Phase 1 deliberately has no CLI or workflow command that admits an amendment. The schemas and chain
rules establish the boundary, while durable amendment-event admission is a Phase 2 concern.
