# QuantForge AI

**An autonomous research tribunal for falsifiable, reproducible quantitative claims.**

Quantitative research often fails because a result is allowed to outrun its protocol, evidence,
or reproducibility. QuantForge asks one governed question: **Does this quantitative claim deserve
to be believed?**

Investment committees debate what to trade. QuantForge audits whether the evidence deserves trust.

Most financial AI searches for strategies to believe. QuantForge searches for reasons not to
believe them.

QuantForge is not an AI investment committee, finance chatbot, strategy generator, trading system,
or free-form agent swarm. Phase 1 implements an offline, typed, deterministic tribunal: a locked
sequential workflow; human-approved experiment constitutions; validated synthetic evidence; a
typed claim graph; a tamper-evident audit chain; six role contracts; and a pure versioned verdict
policy. Roles may explain evidence, but cannot create evidence, bypass approval, or upgrade verdicts.

Phase 1 deliberately does not include a web UI, live model provider, market-data ingestion, real C++
engine adapter, retrieval system, database, broker integration, order submission, or financial
execution. Its demo fixtures are synthetic validation evidence and make no claim of profitability.

## Offline quick start

Python 3.12 or newer is required.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/quantforge case run-demo --scenario fragile
.venv/bin/quantforge case inspect quantforge-demo-fragile/case.json
.venv/bin/quantforge audit verify quantforge-demo-fragile/audit.jsonl
```

The complete demo bundle contains canonical `case.json`, `claim_graph.json`,
`evidence_ledger.json`, an append-only `audit.jsonl`, and a hash inventory. Available scenarios are
`provisional`, `fragile`, and `inconclusive`.

## Evidence and verdict control

Numerical findings are structured references to facts inside validated evidence objects. Free-form
numerical assertions are rejected at reviewer and Chair boundaries. Every evidence object is bound
to the locked constitution and its content hash. Every substantive final claim must trace through
the claim graph to evidence.

`VerdictPolicy` alone computes `SUPPORTED`, `PROVISIONALLY_SUPPORTED`, `INCONCLUSIVE`, `FRAGILE`, or
`REJECTED`. The Chair receives that result as input and is technically prevented from strengthening
or changing it.

## Quality gates

```bash
scripts/quality.sh
```

Runtime dependencies are transitively pinned with distribution hashes in `requirements.lock`.
Development tools are exact direct pins in `pyproject.toml` and `requirements-dev.in`.

The quality script runs formatting checks, lint, strict type checking, the full test suite with
branch coverage, package build metadata checks, a local secret scan, and dependency audit when the
auditor is available.

## Project status and authorship

This is the Phase 1 governed domain foundation, not a claim of production readiness or an empirical
financial research result. Development is AI-assisted and remains human-directed, reviewed, and
maintained by Mrithunjoy Basumatary. AI systems are not project authors or copyright holders.

See [Architecture](docs/ARCHITECTURE.md), [Governance](docs/GOVERNANCE.md), and
[Security Model](docs/SECURITY_MODEL.md).
