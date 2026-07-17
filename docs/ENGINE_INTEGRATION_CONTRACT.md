# C++ Engine Integration Contract

The protected numerical dependency is `MrithunjoyB/cpp-event-driven-backtester` release `v1.0.0`:

- annotated tag object: `20ac53c5e4b61ae7b431d5bb263f246e35f8d2a2`;
- peeled release target: `2f86b71dbc9f29dbda861942d8afbb10c04b6625`;
- invocation contract: `1.0`;
- numerical methodology: `causal_daily_v3_stochastic_v2`;
- stable RNG identity reported by the executable: `portable_bounded_v1`.

The Phase 2A adapter is research-only and read-only. It neither changes nor builds inside the
protected sibling checkout. A separately reviewed executable is supplied with an expected SHA-256,
and all experiment outputs go to an isolated `quantforge-engine-*` directory outside both
repositories.

The production adapter contract is supported on Linux and macOS only. Windows CI validates the
Python package, frozen database fixtures, and offline mock paths; it does not establish genuine
production C++ adapter execution support on Windows.

## Exact allow-list

The adapter has no command-string API. It executes argument vectors corresponding only to:

```text
quant_cli version
quant_cli validate-config --config configs/portfolio_equal_weight.json
quant_cli print-resolved-config --config configs/portfolio_equal_weight.json
quant_cli run --config configs/portfolio_equal_weight.json --dry-run
quant_cli run --config configs/portfolio_equal_weight.json --execution-mode serial --threads 1
python scripts/validate_results.py
```

The `python` label documents the normalized contract; execution uses the current trusted Python
interpreter and the release validator copied from the verified tag. Processes use `shell=False`, an
explicit working directory, stdin isolation, a minimal environment, `C` locale, UTC timezone,
timeouts, output caps, process-group termination, and return-code checks. Arbitrary arguments,
configuration paths, input paths, commands, environment inheritance, and symlinks are rejected.

## Identity and staging

Before every identity query or run the adapter checks the approved remote, clean tracked tree,
annotated tag object, peeled target, release-relative config/input/validator diff, executable regular
file and executable bit, executable size/digest, version, methodology, and RNG lines. The only inputs
are the fixed equal-weight config and six public synthetic files. Each is copied with no-follow and
inode/replacement checks, bounded size, exclusive destination creation, and `fsync`.

Version discovery runs in a separate identity directory, never with the protected repository as
the child working directory. The adapter snapshots repository root/common directory, remote, HEAD,
branch, tag object/target/type, every ref, tracked and staged diffs, status, and content-hashed
tracked/untracked/ignored inventories before and after execution. Every engine and validator child
is followed by exact config/input/validator byte and semantic rehashing, staged inventory/type and
symlink checks, and executable/validator identity checks. Staged inputs are made read-only where the
host permits; post-child verification remains authoritative.

Successful execution alone is insufficient. Admission additionally requires the exact config/input
semantic and byte hashes, a complete bounded output inventory, supported JSON/CSV schema versions,
the release `validate_results.py` result, finite decimal facts at declared CSV locations, closed
units, and methodology metadata. The resulting bundle must match the locked constitution, case,
workflow revision, amendment-chain head, engine identity, and prior-bundle head.

Successful execution issues a one-shot, code-owned `cpp-v1-adapter/2.0` receipt in memory. The
receipt binds the case/revision, constitution/amendments, release identities, executable, config,
inputs, outputs, validator execution, invocation, and repository snapshot. Only
`engine execute-and-admit-fixture` / `execute_and_admit_engine_evidence()` can consume it while
constructing and atomically admitting the actual run. It is not a JSON model and cannot be supplied
through CLI text, bundle fields, or database rows. Delayed and cross-process admission are
unsupported. `evidence verify` remains a structural integrity operation; `evidence admit` rejects
rather than offering a weaker fallback.

The C++ engine remains authoritative for numerical values; QuantForge validates and cites those
values without recalculating or strengthening them. Failed identity, schema, validation, provenance,
or inventory checks fail closed and cannot be repaired by prose.
