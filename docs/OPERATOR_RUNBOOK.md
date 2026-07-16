# Phase 2A Operator Runbook

Use a reviewed Python 3.12 environment and an independently built executable from the exact protected
C++ `v1.0.0` tag. Never point the adapter at a mutable work product or a user-supplied executable.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
.venv/bin/python -m pip install -e . --no-deps --no-build-isolation
.venv/bin/quantforge store init research.sqlite3
.venv/bin/quantforge store inspect research.sqlite3
.venv/bin/quantforge store validate research.sqlite3
.venv/bin/quantforge store migrate research.sqlite3 --dry-run
```

Initialize the bounded synthetic case, verify the release, and execute the approved fixture:

```bash
.venv/bin/quantforge case initialize-fixture \
  --store research.sqlite3 --scenario provisional
.venv/bin/quantforge engine verify-release \
  --repository /trusted/cpp-event-driven-backtester \
  --executable /trusted/build/quant_cli \
  --expected-executable-sha256 <reviewed-64-character-sha256> \
  --work-root /trusted/empty-work-root
.venv/bin/quantforge engine execute-fixture \
  --repository /trusted/cpp-event-driven-backtester \
  --executable /trusted/build/quant_cli \
  --expected-executable-sha256 <reviewed-64-character-sha256> \
  --work-root /trusted/empty-work-root \
  --store research.sqlite3 --case-id case_provisional \
  --bundle-output bundle.json
```

The execution response prints the isolated `artifact_root`. Preserve it until independent bundle
verification and admission finish. Use the identical release arguments with:

```bash
.venv/bin/quantforge evidence verify \
  --repository /trusted/cpp-event-driven-backtester \
  --executable /trusted/build/quant_cli \
  --expected-executable-sha256 <reviewed-64-character-sha256> \
  --work-root /trusted/empty-work-root \
  --store research.sqlite3 --case-id case_provisional \
  --bundle-file bundle.json --artifact-root <printed-artifact-root>
.venv/bin/quantforge evidence admit \
  --repository /trusted/cpp-event-driven-backtester \
  --executable /trusted/build/quant_cli \
  --expected-executable-sha256 <reviewed-64-character-sha256> \
  --work-root /trusted/empty-work-root \
  --store research.sqlite3 --case-id case_provisional \
  --bundle-file bundle.json --artifact-root <printed-artifact-root> \
  --evidence-id evidence_cpp_v1
.venv/bin/quantforge case reconstruct \
  --store research.sqlite3 --case-id case_provisional
.venv/bin/quantforge case export \
  --store research.sqlite3 --case-id case_provisional --output-dir case-package
.venv/bin/quantforge case verify-package case-package
```

The CLI does not accept a raw command fragment. Run exports only to new empty paths. Back up the
SQLite file and WAL consistently while no writer is active, or use SQLite's backup API; copying a
live database file alone is unsafe.

On any identity, migration, integrity, replay, hash, schema, or revision failure, stop. Preserve the
database, WAL/SHM, bundle, adapter logs, and artifact root read-only; do not edit records or retry with
weaker checks. Compare against a trusted backup/digest and investigate before creating a new store.

This runbook does not authorize broker access, orders, live trading, investment advice, market-data
ingestion, a live provider, or profitability claims.
