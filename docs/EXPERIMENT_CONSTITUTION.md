# Experiment Constitution

The constitution is the scientific contract that prevents results-driven protocol drift. It embeds
the complete proposal, explicit human approval, lock timestamp, schema version, stable identity, and
a SHA-256 digest of canonical JSON.

The approval records the exact proposal digest. Constitution construction rejects a negative or
mismatched approval, and validation recomputes both proposal and constitution identities. Frozen
models prevent in-process field mutation after lock.

Amendments are separate append-only objects classified as `reviewer_requested`, `exploratory`, or
`administrative`. Each records author role, timestamp, reason, changes, parent constitution hash, and
its own canonical hash. Amendment validation rejects keys that attempt to rewrite primary or null
hypotheses. Exploratory findings remain separate from the primary proposal; an amendment never
changes the original constitution object.
