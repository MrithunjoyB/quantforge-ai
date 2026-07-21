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
- The flagship governed demo uses deterministic mock output only. The optional official structured
  provider surface is not called or live-verified by the demo; live verification requires separate
  operator authorization and credentials.
- The Phase 2B.3 comparative suite also uses deterministic mock output. Its perfect expected fixture
  routing is a harness-conformance result, not evidence about model intelligence, reasoning,
  provider refusal behavior, structured-output reliability, token cost, latency, or general quality.
- The 24 synthetic cases are curated and heterogeneous, with one clean control; they do not support
  population confidence intervals, global ranking, or a claim that QuantForge is broadly superior.
- Live comparative transport is not executed or exposed by Phase 2B.3. The fail-closed plan,
  authorization, six-call receipt, call budget, cost cap, checkpoint, and result-namespace controls
  require a separately reviewed activation using the existing official OpenAI provider.
- Mock and live quality metrics are separate populations and cannot be compared as equivalent.
  Global competitiveness requires later live evaluation and external reproduction.
- Trusted engine admission is same-process only. Delayed and cross-process bundle admission are
  deliberately unsupported; standalone verification does not establish execution authenticity.
- There is no external market-data ingestion, retrieval service, web UI, dashboard, vector store,
  broker connectivity, order submission, execution venue, live trading, investment advice,
  profitability assertion, or profitability guarantee.
- Process controls are a narrow application boundary, not a container or hostile-OS sandbox.
- A fully rehashed replacement by an attacker controlling all local state needs a separately trusted
  digest, signed publication, or backup to detect.
