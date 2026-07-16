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

Successful execution alone is insufficient. Admission additionally requires the exact config/input
semantic and byte hashes, a complete bounded output inventory, supported JSON/CSV schema versions,
the release `validate_results.py` result, finite decimal facts at declared CSV locations, closed
units, and methodology metadata. The resulting bundle must match the locked constitution, case,
workflow revision, amendment-chain head, engine identity, and prior-bundle head.

The C++ engine remains authoritative for numerical values; QuantForge validates and cites those
values without recalculating or strengthening them. Failed identity, schema, validation, provenance,
or inventory checks fail closed and cannot be repaired by prose.
