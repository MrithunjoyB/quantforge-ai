# Evidence Model

Every admitted evidence object records stable schema and case identities, related claims and
experiment, locked constitution hash, adapter, safe artifact path, source byte digest, structured
fact location, content digest, UTC timestamp, validation method, decimal facts, closed units,
assumptions, limitations, relationship, and provenance. The ledger is append-only and rejects
foreign bindings or replacement identifiers. The claim graph is typed, acyclic, ledger-checked, and
requires each substantive final claim to reach validated evidence.

## Engine evidence bundle 1.0

An engine bundle has two explicitly separated, canonical halves:

- semantic: bundle/case/workflow/constitution/amendment identities; exact C++ repository, release,
  tag, target, and executable digest; invocation-contract version and normalized arguments; config
  digest; ordered input/output semantic inventories and schema versions; validator result digests;
  numeric fact references, decimal values, units, methodology IDs; and previous bundle hash;
- observations: execution/admission timestamps, ordered input/output byte digests and sizes, and
  bounded process stdout/stderr digests.

`semantic_hash` and `observation_hash` are calculated independently. `bundle_hash` binds both hashes.
Root-level JSON output semantics exclude only the documented volatile keys `actual_commit`, `elapsed_seconds`,
`generated_at`, `generated_at_utc`, `git_commit_hash`, `hostname`, `output_directory`,
`portfolio_output_directory`, `run_timestamp_utc`, `source_tree_status`, `timestamp`, and `username`.
Their original bytes remain in the observation inventory and therefore in the bundle hash. The
exclusion is path-specific: a same-named nested field remains semantic. CSV values and all
nonvolatile JSON values remain semantic.

The optional signer interface authenticates the bundle hash. `HmacSha256TestSigner` is only a local
fixture signer: hashing proves integrity relationships, not who created a bundle, and no production
secret is embedded or generated.

Admission verifies every referenced CSV location and requires its finite canonical decimal to equal
the declared fact exactly. It checks complete file inventory, byte and semantic hashes, supported
schemas/methodology, monotonic/bounded timestamps, current case and constitution state, workflow
revision, amendment chain, engine/config/input identities, and bundle-chain parent. Only then is a
normal `EvidenceObject` created; the numerical value is copied, not reinterpreted.

Bundle integrity does not prove that a process ran. Execution authenticity requires the separate,
non-serializable, one-shot trusted receipt retained by the approved adapter and consumed by the
same-process execute-and-admit operation. Serialized and self-declared validator results can be
structurally verified but cannot enter the evidence ledger through standalone admission.

Bundle IDs and hashes are immutable unique database keys. Bundle order and each previous hash are
rechecked during reconstruction and independent package verification. Duplicate, reordered,
truncated, cross-case, stale, substituted, or post-finalization evidence fails closed.
