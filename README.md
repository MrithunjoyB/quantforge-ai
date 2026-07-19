# QuantForge AI

**A governed, deterministic research tribunal for falsifiable quantitative claims.**

Quantitative research can fail when a result outruns its protocol, evidence, or reproducibility.
QuantForge AI runs an offline, code-governed tribunal that locks the experiment constitution,
validates synthetic evidence, preserves contradictory findings, replays an audit chain, and lets a
pure policy compute the strongest defensible verdict.

> Investment committees debate what to trade. QuantForge audits whether the evidence deserves
> trust.

> Most financial AI searches for strategies to believe. QuantForge searches for reasons not to
> believe them.

This repository contains the independently audited **Phase 1 governance foundation** and the Phase
2A durable local case store plus research-only C++ v1.0.0 evidence adapter. The first bounded Phase
2B stage adds an optional official OpenAI strict-structured provider and six governed role contracts.
Version `v0.1.0` remains the immutable Phase 1 release. The Phase 2B2 flagship demonstration runs
the six governed role contracts through genuine C++ evidence admission, durable reconstruction, and
an independently verifiable artifact set. Roles may propose or explain, but code owns workflow
state, evidence validity, human approval, constitutions, and verdict strength.

## Flagship governed tribunal demonstration

The professional offline case starts with an attractive synthetic performance claim and then shows
why it remains `INCONCLUSIVE`: corrected inference, drawdown, loss probability, concentration, and
regime objections outweigh the headline return. It uses the deterministic mock provider through the
real Phase 2B contracts and the protected C++ `v1.0.0` execute-and-admit path. It performs no network
or live-model call.

```bash
.venv/bin/quantforge demo run \
  --repository /absolute/path/to/cpp-event-driven-backtester \
  --executable /absolute/outside/build/directory/quant_cli \
  --expected-executable-sha256 <reviewed-64-character-sha256> \
  --work-root /private/tmp \
  --output-dir /private/tmp/quantforge-governed-tribunal
.venv/bin/quantforge demo verify /private/tmp/quantforge-governed-tribunal
```

The exact digest command, platform notes, runtime, evidence interpretation, artifact inventory, and
offline-versus-live boundary are in the
[governed tribunal demo runbook](docs/GOVERNED_TRIBUNAL_DEMO.md).

After the locked development environment is installed, the exact offline demo command is:

```bash
.venv/bin/quantforge case run-demo --scenario fragile --output-dir quantforge-demo-fragile
```

The command uses packaged synthetic fixtures, performs no network request, and exports canonical
case, evidence, claim-graph, manifest, and audit artifacts. Those artifacts are validation evidence
for governance behavior—not financial evidence and not evidence of profitability.

Phase 2A adds a schema-versioned SQLite backend, deterministic case packages, and one narrowly
allow-listed, read-only adapter for the protected C++ `v1.0.0` public synthetic fixture. The C++
release remains the numerical authority. OpenAI mode is disabled by default, has no tool access, and
requires an explicit operator model and environment credential. There is no external market-data
ingestion, retrieval system, web UI, broker connectivity, order submission, live trading,
production deployment, investment advice, profitability claim, or guarantee.

## Install and verify offline behavior

Python 3.12 or newer is required. The reviewed development lock includes exact versions and hashes
for runtime, test, build, audit, and release tools.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
.venv/bin/python -m pip install -e . --no-deps --no-build-isolation
.venv/bin/quantforge --version
.venv/bin/quantforge case run-demo --scenario fragile --output-dir quantforge-demo-fragile
.venv/bin/quantforge case validate quantforge-demo-fragile/case.json \
  --audit-file quantforge-demo-fragile/audit.jsonl
.venv/bin/quantforge audit verify quantforge-demo-fragile/audit.jsonl
```

Available synthetic scenarios are `provisional`, `fragile`, and `inconclusive`. Run all three with
`examples/run_all_demos.sh`.

## Governance and evidence boundary

The workflow is sequential and code-owned. A human-approved experiment constitution is locked
before evaluation. Numerical findings must be structured references to facts inside validated,
hashed evidence objects; free-form numerical assertions are rejected. Evidence is bound to the
case, experiment, constitution, source artifact, and digest. Every substantive final claim must
trace through a typed acyclic claim graph to the evidence ledger.

`VerdictPolicy` alone computes `SUPPORTED`, `PROVISIONALLY_SUPPORTED`, `INCONCLUSIVE`, `FRAGILE`, or
`REJECTED`. The Chair receives the computed result and cannot strengthen or replace it. Complete,
single-case semantic audit replay is required to restore or validate an advanced case state.

The local audit chain is tamper-evident but is not signed or externally anchored. Whole-artifact-set
replacement by an attacker who controls every local file remains a documented Phase 2 boundary.

## Quality and release-candidate checks

```bash
scripts/quality.sh
```

The quality gate checks formatting, Ruff, strict mypy, full branch-aware pytest coverage, the 90%
combined governance-critical coverage floor (including provider, CLI, storage, and engine), plus
per-module provider/orchestrator floors, malicious-input regressions, repository/document/version
contracts, CFF validity, secret patterns, and source/wheel
builds. Dependency vulnerability checks are enabled with `RUN_DEPENDENCY_AUDIT=1`.

After committing an exact candidate, deterministic local release artifacts are produced with:

```bash
.venv/bin/python -m scripts.release_candidate \
  --baseline-commit <audited-40-character-commit> \
  --output-dir release/v0.1.0
```

Generated distributions, CycloneDX SBOM, checksums, validation reports, demos, caches, and temporary
environments are ignored. The transactional process and required future GitHub authorization are
defined in [Release Policy](docs/RELEASE_POLICY.md).

## Project status and documentation

Version `0.1.0` communicates an audited Phase 1 governance foundation, not a production-ready
QuantForge Platform or an empirical financial research result. Development is AI-assisted and
remains human-directed, reviewed, and maintained by Mrithunjoy Basumatary. AI systems are not
project authors or copyright holders.

- [Architecture](docs/ARCHITECTURE.md)
- [Offline governed tribunal demonstration](docs/GOVERNED_TRIBUNAL_DEMO.md)
- [Phase 2B structured provider contract](docs/PHASE_2B_PROVIDER_CONTRACT.md)
- [Six governed role contracts](docs/ROLE_CONTRACTS.md)
- [OpenAI provider runbook](docs/OPENAI_PROVIDER_RUNBOOK.md)
- [Phase 2B provider threat model](docs/PHASE_2B_THREAT_MODEL.md)
- [Storage model](docs/STORAGE_MODEL.md)
- [Migration policy](docs/MIGRATION_POLICY.md)
- [C++ engine integration contract](docs/ENGINE_INTEGRATION_CONTRACT.md)
- [Evidence model](docs/EVIDENCE_MODEL.md)
- [Deterministic semantics](docs/DETERMINISM.md)
- [Operator runbook](docs/OPERATOR_RUNBOOK.md)
- [Limitations](docs/LIMITATIONS.md)
- [Governance](docs/GOVERNANCE.md)
- [Security Model](docs/SECURITY_MODEL.md)
- [Threat Model](docs/THREAT_MODEL.md)
- [Phase 1 independent audit](audit/phase1_independent_audit.md)
- [v0.1.0 release notes](docs/RELEASE_NOTES_v0.1.0.md)
- [Contributing](CONTRIBUTING.md)
- [Security reporting](SECURITY.md)
- [Support policy](SUPPORT.md)

Licensed under Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
