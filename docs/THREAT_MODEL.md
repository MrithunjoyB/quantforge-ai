# Threat Model

| Threat | Control | Residual limitation |
| --- | --- | --- |
| Prompt injection | No live model; future providers remain behind typed role authority | Provider-specific evaluation is Phase 2B work |
| SQL injection | No raw query surface; parameter binding; fixed migrations and table names | Filesystem access to the DB must be controlled by the operator |
| Schema downgrade/future/partial migration | Application ID, `user_version`, metadata, ordered checksummed history, exact schema fingerprint | A supported migration still requires normal code review |
| Concurrent/stale writer | `BEGIN IMMEDIATE`, busy timeout, optimistic case revision in the update predicate | Local SQLite is not distributed consensus |
| Database replacement/corruption | inode checks around operations, integrity/FK checks, replay and materialization hashes | Total trusted-file replacement needs an external digest or backup to detect |
| Evidence or output substitution | case/revision/constitution/amendment/engine/config/input bindings; exact output inventory and hashes | Source truth depends on the protected numerical release |
| Bundle replay/reorder/truncation | unique bundle IDs/hashes, monotonic sequence, previous-bundle hash, reconstruction checks | There is no cross-installation nonce service |
| Forged numerical claim | validated CSV location, finite canonical decimal equality, closed unit and methodology | QuantForge does not independently recompute engine mathematics |
| Executable/command substitution | exact digest and version lines; tuple allow-list; no shell or raw fragments | Compiler/toolchain provenance is outside the bundle |
| Environment poisoning | explicit environment allow-list, UTC, `C` locale, isolated HOME/TMP | OS-level process isolation is not a container sandbox |
| Timeout/output flood | wall timeout, output caps, process-group termination, file/row/count limits | Disk quotas remain operator-controlled |
| Path traversal/symlink race | normalized relative schemas, component checks, no-follow source open, inode comparison | Same-host privileged attackers remain out of scope |
| Malformed JSON/CSV/non-finite values | bounded strict parsers, duplicate/header/row/schema checks, decimal canonicalization | Resource isolation beyond configured limits is OS-owned |
| Audit/graph/verdict tampering | complete event replay, hash chain, materialization and ledger/graph checks, pure verdict policy | A fully rehashed history needs an external trust anchor |
| Post-finalization injection | finalized flag, workflow rules, store append rejection, admission context check | No reopening workflow exists in Phase 2A |
| Secrets exposure | no provider secret or embedded signing key; repository secret scan | Optional production signing/secret management is not implemented |
| Accidental real trading | no market-data ingestion, broker, order, execution, or live-trading capability | Any future execution work remains explicitly prohibited |
