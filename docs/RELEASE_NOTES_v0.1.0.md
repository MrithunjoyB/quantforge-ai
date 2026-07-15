# QuantForge AI v0.1.0 Release Notes

## Audited Phase 1 governance foundation

Version `0.1.0` is the first publication candidate for QuantForge AI's offline governance core.
It asks whether quantitative evidence deserves trust by enforcing a deterministic tribunal around
experiment approval, evidence lineage, adversarial review, reproducibility, and conservative
verdicts.

The independent Phase 1 audit passed after all identified High and Medium findings were repaired and
regression-tested. The release adds publication-grade dependency locks, documentation, immutable
GitHub Action pins, multi-platform CI definitions, security and CodeQL analysis, repeated scenario
reproducibility checks, deterministic distributions, an installed-wheel smoke test, a CycloneDX 1.6
SBOM, SHA-256 checksums, and machine/human validation reports.

## What is included

- strict immutable domain schemas and canonical JSON identity;
- a code-owned 12-state workflow with explicit actor/action authority;
- human-approved experiment constitutions and amendment lineage controls;
- evidence objects bound to case, experiment, constitution, content, source path, and digest;
- a typed acyclic claim graph reconciled with the evidence ledger;
- complete single-case semantic audit replay;
- a pure bounded `VerdictPolicy` that roles cannot upgrade;
- three byte-stable synthetic demo scenarios and an offline CLI;
- wheel and source distributions with Apache-2.0 license and notice material.

## Exact offline demo

After installing the reviewed lock and project as described in the README:

```bash
.venv/bin/quantforge case run-demo --scenario fragile --output-dir quantforge-demo-fragile
```

The scenario is synthetic. Its output validates governance behavior and makes no empirical return,
risk, strategy-quality, or profitability claim.

## Security and supply chain

Runtime dependency resolution is exactly pinned and hash-locked. Development, build, audit, CFF,
SBOM, test, lint, and type-check tools are reproducible under `requirements-dev.lock`. Release
artifacts are inspected, checksummed, represented in the SBOM/validation reports, and tested outside
the source tree. GitHub workflows grant read-only repository access except CodeQL's narrowly scoped
`security-events: write` result upload.

## Deliberate limitations

This is not the complete QuantForge Platform and is not production-ready. It has no live provider or
real OpenAI execution, real C++ engine integration, market-data ingestion, retrieval, persistence,
UI, broker connectivity, order submission, live trading, autonomous investment authority, or
investment advice. Audit nonrepudiation is local rather than externally signed or anchored.

No tag, GitHub repository, remote, push, release, or uploaded asset is created by preparation of this
local candidate. Those steps require separate user authorization and the exact process in
[Release Policy](RELEASE_POLICY.md).
