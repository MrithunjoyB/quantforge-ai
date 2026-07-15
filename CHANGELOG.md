# Changelog

All notable changes follow the principles of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses semantic versioning for publication identifiers while its schema and verdict
policy versions remain independently governed.

## [Unreleased]

No changes recorded.

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
