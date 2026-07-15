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

This is the independently audited **Phase 1 governance foundation**, prepared as a local `v0.1.0`
publication candidate. It is not an AI investment committee: roles may propose or explain, but
code owns workflow state, evidence validity, human approval, and verdict strength.

After the locked development environment is installed, the exact offline demo command is:

```bash
.venv/bin/quantforge case run-demo --scenario fragile --output-dir quantforge-demo-fragile
```

The command uses packaged synthetic fixtures, performs no network request, and exports canonical
case, evidence, claim-graph, manifest, and audit artifacts. Those artifacts are validation evidence
for governance behavior—not financial evidence and not evidence of profitability.

Current limitations are deliberate: there is no live model provider, real OpenAI execution,
market-data ingestion, real C++ engine integration, database, retrieval system, web UI, broker
connectivity, order submission, live trading, production deployment, or investment advice.

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

The quality gate checks formatting, Ruff, strict mypy, full branch-aware pytest coverage, the
governance-critical coverage floor, malicious-input regressions, repository/document/version
contracts, CFF validity, secret patterns, and source/wheel builds. Dependency vulnerability checks
are enabled with `RUN_DEPENDENCY_AUDIT=1`.

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
- [Governance](docs/GOVERNANCE.md)
- [Security Model](docs/SECURITY_MODEL.md)
- [Threat Model](docs/THREAT_MODEL.md)
- [Phase 1 independent audit](audit/phase1_independent_audit.md)
- [v0.1.0 release notes](docs/RELEASE_NOTES_v0.1.0.md)
- [Contributing](CONTRIBUTING.md)
- [Security reporting](SECURITY.md)
- [Support policy](SUPPORT.md)

Licensed under Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
