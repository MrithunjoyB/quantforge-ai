# Limitations

Phase 2A is local, offline, research-only infrastructure. It is not a production service or trading
system.

- The adapter is read-only and supports one fixed public synthetic C++ v1.0.0 fixture. It does not
  accept user-selected configurations, data, commands, or result paths.
- Genuine production adapter execution is supported on Linux and macOS. Windows validation covers
  packaging, historical fixtures, and mock/offline Python paths, not production C++ execution.
- C++ v1.0.0 remains the numerical authority. QuantForge validates and cites its output but does not
  independently recompute its portfolio or statistical methods.
- SQLite supplies single-host durability, not replication, distributed locking, remote recovery,
  hardware-backed keys, or an external tamper anchor. Operators own permissions and backups.
- HMAC signing exists for tests only. There is no production signing key, PKI, transparency log, or
  trusted timestamp service.
- There is no live OpenAI or other model provider. Structured provider integration is a later phase.
- Trusted engine admission is same-process only. Delayed and cross-process bundle admission are
  deliberately unsupported; standalone verification does not establish execution authenticity.
- There is no external market-data ingestion, retrieval service, web UI, dashboard, vector store,
  broker connectivity, order submission, execution venue, live trading, investment advice,
  profitability assertion, or profitability guarantee.
- Process controls are a narrow application boundary, not a container or hostile-OS sandbox.
- A fully rehashed replacement by an attacker controlling all local state needs a separately trusted
  digest, signed publication, or backup to detect.
