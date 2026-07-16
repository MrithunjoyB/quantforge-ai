# Security Model

QuantForge uses deny-by-default integration boundaries. There is no network client, API key, live
provider, market feed, broker, order domain, shell tool, arbitrary code executor, unsafe
deserializer, or writable engine adapter. Mock roles receive typed domain objects, not filesystem or
process capabilities.

Untrusted JSON is bounded UTF-8 and rejects duplicate keys, floats where canonical decimal strings
are required, non-finite values, excess depth/size, unknown fields, unsafe paths, control characters,
and invalid identities. Canonical JSON normalizes Unicode, timestamps, decimals, and negative zero.
Outputs use private unpredictable temporary files, atomic replacement, and component-wise symlink
rejection.

The SQLite backend is not a general SQL interface. Every value uses parameter binding; schema names
and migrations are compiled constants. It enables foreign keys, WAL, full synchronous durability,
trusted-schema restrictions, bounded busy waits, transaction-scoped revision checks, immutable
identifiers, schema/application IDs, migration checksums, schema fingerprints, integrity checks,
resource limits, event replay, and materialization cross-checks. Unknown, partial, modified, future,
replaced, or oversized stores fail closed. SQLite files still require OS-level access control and a
trusted backup/digest for recovery from total local compromise.

The engine boundary validates the exact release, approved paths, executable digest/version, command
tuple, minimal environment, process limits, input staging, result schemas, release validator,
artifact inventory, digests, and numeric locations. It never uses `shell=True` or raw fragments.
Engine results are not evidence until case-state-bound transactional admission succeeds.

Free text is not numerical evidence. State transitions, role authority, and verdict strength remain
code-owned. This is research infrastructure, not a trading system; there is no profitability claim
or guarantee.
