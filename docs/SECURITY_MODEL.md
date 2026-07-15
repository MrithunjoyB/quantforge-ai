# Security Model

Phase 1 uses deny-by-default integration boundaries. There is no network client, API key, broker,
market feed, shell tool, arbitrary code executor, database, unsafe deserializer, or writable engine
adapter. Mock roles receive domain objects, not filesystem or process capabilities.

Inputs are bounded UTF-8 JSON. Duplicate keys, floats, non-finite values, excess size or depth,
unknown schema fields, unsafe paths, symlinks, invalid hashes, foreign identities, and malformed
enums are rejected. Output uses canonical JSON and refuses symlink replacement. Evidence content,
constitutions, amendments, and audit events are independently hash-verified.

Free text is not evidence. Numeric claims use validated fact references. State transitions and role
authority are code-owned. Verdict strength is code-owned. Synthetic fixtures are package resources,
not user-controlled external commands or artifact locations.
