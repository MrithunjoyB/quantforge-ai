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

Initialize the bounded synthetic case, verify the release, then execute and admit through the
same-process trusted path:

```bash
.venv/bin/quantforge case initialize-fixture \
  --store research.sqlite3 --scenario provisional
.venv/bin/quantforge engine verify-release \
  --repository /trusted/cpp-event-driven-backtester \
  --executable /trusted/build/quant_cli \
  --expected-executable-sha256 <reviewed-64-character-sha256> \
  --work-root /trusted/empty-work-root
.venv/bin/quantforge engine execute-and-admit-fixture \
  --repository /trusted/cpp-event-driven-backtester \
  --executable /trusted/build/quant_cli \
  --expected-executable-sha256 <reviewed-64-character-sha256> \
  --work-root /trusted/empty-work-root \
  --store research.sqlite3 --case-id case_provisional \
  --evidence-id evidence_cpp_v1 --bundle-output bundle.json
```

`execute-fixture` and `evidence verify` may be used separately for structural inspection, but the
resulting serialized bundle cannot be admitted. `evidence admit` deliberately fails because a file
cannot carry the in-process execution capability. Delayed and cross-process admission are
unsupported. After trusted admission, continue with:

```bash
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

Run the production adapter only on Linux or macOS. Windows validation covers packaging, frozen
fixtures, and mock/offline Python paths, not production C++ adapter execution.
