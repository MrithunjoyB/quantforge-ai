# Future Engine Integration Contract

The protected dependency is `cpp-event-driven-backtester` release `v1.0.0`.

- Annotated tag object: `20ac53c5e4b61ae7b431d5bb263f246e35f8d2a2`
- Release commit: `2f86b71dbc9f29dbda861942d8afbb10c04b6625`
- Integration status: disabled in Phase 1

The future read-only adapter may invoke only reviewed argument arrays for the documented
`validate-config`, `print-resolved-config`, `run --dry-run`, and `run` CLI forms. It must never accept
a command string or shell expansion. Inputs and outputs use explicit normalized paths inside an
isolated run directory. The adapter must confirm the release identity, executable digest, resolved
configuration, input and manifest hashes, output inventory, schemas, validator results, and
provenance before producing evidence.

The C++ release is the numerical authority. An LLM cannot modify engine source, configuration after
constitution lock, canonical outputs, manifests, or validators. Failed schemas, hashes, provenance,
or reconstruction produce failed evidence; they are never repaired by prose. The sibling repository
must not be a writable submodule or copied implementation.

This contract is derived read-only from release documentation at `v1.0.0`, including
`docs/CONFIGURATION.md`, `docs/RESULT_SCHEMA.md`, and `docs/REPRODUCIBILITY.md`. No adapter code or
engine source is copied here.
