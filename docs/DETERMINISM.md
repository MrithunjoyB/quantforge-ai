# Deterministic Semantics

QuantForge distinguishes semantic identity from observations that necessarily vary between runs.

- Canonical JSON sorts object keys and normalizes Unicode, UTC timestamps, finite decimals, and
  negative zero.
- Audit event hashes, case semantic hashes, materialization hashes, migration checksums, artifact
  semantic hashes, and export manifests use canonical JSON.
- Engine bundle semantic hashes contain every meaningful input, invocation, schema, validator,
  output value, methodology, unit, and lineage identity.
- Execution/admission time and raw byte observations have a separate observation hash. Documented
  volatile JSON provenance fields are removed only from semantic artifact hashing; their original
  artifact bytes remain byte-hashed in observations and therefore remain bound by the bundle hash.
- Exports include no export-time clock. Their ID derives from case ID and revision; parent lineage is
  the prior durable manifest; artifacts and manifest end in one normalized newline.

Repeated approved fixture execution must produce identical output semantics, numeric facts,
validator identity, config/input identity, and canonical semantic bundle bytes. Observation and full
bundle hashes may differ when truthful timestamps or raw volatile bytes differ. Re-exporting the
same revision to new empty directories must be byte-identical. Reconstructing from events must equal
the stored case, ledger, graph, verdict result, and audit head. Migration must not change those
semantic identities.

Tests exercise repeated fake and real tagged-engine runs, repeat export, independent package
verification, serial full-suite runs, reversed file order, and branch-aware coverage. This design
does not claim bit-identical executables across compilers or remove meaningful provenance to create
an artificial deterministic result.
