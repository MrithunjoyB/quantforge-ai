# Migration Policy

Durable schemas advance forward only. Each migration has an integer version, stable name, fixed SQL
statement tuple, and canonical SHA-256 checksum compiled into QuantForge. The database must contain
exactly one ordered history row per applied version, and its metadata version, SQLite `user_version`,
known schema-object set, and schema fingerprint must agree.

Migration rules are:

1. refuse uninitialized foreign databases, unknown future versions, altered checksums, missing or
   extra objects, partial histories, and metadata/version disagreement;
2. apply one version per explicit transaction and update history/metadata/version in that same
   transaction;
3. rollback the version on any error and validate the complete resulting schema;
4. make migration of an already-current store an inspected no-op;
5. provide `--dry-run` by backing up into memory, applying all pending migrations there, and fully
   validating the result without mutating the source file;
6. never downgrade, silently repair, or discard unknown data.

Phase 2A includes genuine frozen schema-1 and schema-2 databases created directly with the baseline
runtime, not downgraded from candidate code. Metadata records each original database digest,
migration checksum, schema fingerprint, origin commit, and expected semantic/audit/graph identities.
Tests copy each fixture, perform dry-run and real migration to schema 4, and prove those identities
are unchanged. Adversarial tests cover partial history, future values, modified schema SQL, and
repeat migration.

Future migrations must add a historical fixture and the same semantic-invariance proof before the
latest schema constant changes. Destructive or lossy transformations require a separately governed
export/recovery design and are not permitted by this framework.
