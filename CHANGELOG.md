# Changelog

All notable changes follow the principles of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses semantic versioning for publication identifiers while its schema and verdict
policy versions remain independently governed.

## [Unreleased]

### Added

- Add a closed, versioned 24-case quantitative-research benchmark and seven-case judge subset with
  separate public inputs, code-owned ground truth, deterministic provider fixtures, and semantic and
  provenance hashes.
- Add fair single-agent and planner–reviewer baselines plus a real six-role QuantForge evaluation
  adapter, exact component scoring, deterministic repeat evidence, and closed report export,
  independent verification, and replay commands.
- Add offline comparison CLI commands and fail-closed future-live planning, model/call/cost approval,
  six-call receipt, budget-exhaustion, checkpoint, and result-namespace controls.
- Add a backend-neutral durable case-store contract, crash-safe SQLite backend, forward-only
  checksummed migrations, historical fixture, deterministic reconstruction, and export lineage.
- Add a read-only adapter for the exact protected C++ v1.0.0 public synthetic fixture and canonical
  engine-evidence bundles with optional fixture-only signing.
- Add narrowly scoped store, migration, engine, evidence, reconstruction, and package CLI commands.
- Add adversarial storage/bundle/process tests and Linux/macOS tagged-engine integration CI.

### Security

- Structurally exclude benchmark ground truth from provider-accessible case models, reject foreign
  evidence and identity substitution, independently recompute exported scores and metrics, and add
  the complete evaluation namespace to the 90% governance-critical branch-coverage gate.
- Bind engine evidence to release, executable, invocation, configuration, inputs, complete outputs,
  validators, methodology, case, workflow revision, constitution, amendments, and bundle lineage.
- Reject injection, stale writers, schema tampering, path/symlink attacks, substitution, malformed or
  non-finite output, process flooding, audit/graph drift, and post-finalization admission.

### Limitations

- Comparative results are offline deterministic mock-provider conformance evidence, not live-model
  quality, global competitiveness, cost, or latency evidence. Live comparative transport remains
  disabled pending separate official-OpenAI verification and reviewed activation.
- The adapter is research-only, read-only, and limited to one public synthetic fixture. Live
  providers, market data, brokers, orders, live trading, investment advice, and profitability claims
  remain out of scope.

## [0.1.0] - 2026-07-15

### Added

- Publish the audited Phase 1 governance foundation: immutable constitutions, typed evidence,
  claim graphs, a deterministic workflow, a semantic audit chain, bounded role contracts, synthetic
  demos, and a code-owned verdict policy.
- Add professional contribution, conduct, security, support, citation, release-policy, release-note,
  CI, security, reproducibility, and release-candidate infrastructure.
- Add deterministic wheel/sdist generation, a CycloneDX 1.6 SBOM, SHA-256 checksums, distribution
  inspection, installed-wheel smoke tests, and machine/human release-validation reports.

### Security

- Repair every High and Medium issue found by the independent Phase 1 audit, including workflow
  authority, semantic audit replay, evidence lineage, claim-graph validity, verdict limits,
  constitution lineage, hostile serialization/path handling, and dependency reproducibility.
- Pin all direct and transitive dependency distributions with hashes and pin every GitHub Action to
  an immutable commit.

### Limitations

- This release contains synthetic, offline governance behavior only. It does not provide real model,
  market-data, engine, broker, order, live-trading, production, or investment-advice capability.

[Unreleased]: docs/RELEASE_POLICY.md
[0.1.0]: docs/RELEASE_NOTES_v0.1.0.md
