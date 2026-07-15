# Security Model

Phase 1 uses deny-by-default integration boundaries. There is no network client, API key, broker,
market feed, shell tool, arbitrary code executor, database, unsafe deserializer, or writable engine
adapter. Mock roles receive domain objects, not filesystem or process capabilities.

Inputs are bounded UTF-8 JSON. Duplicate keys, floats, non-finite values, excess size or depth,
unknown schema fields, unsafe paths, symlink components, invalid hashes, foreign identities, control
characters, extreme decimals, and malformed enums are rejected. Canonical JSON normalizes Unicode,
timestamps, decimals, and negative zero. Output uses private-permission unpredictable temporary files,
atomic replacement, and refuses symlink traversal. Evidence content, source artifacts,
constitutions, amendments, graph bindings, and audit events are independently hash-verified.

Free text is not evidence. Numeric claims use validated fact references. State transitions and role
authority are code-owned. Verdict strength is code-owned. Synthetic fixtures are package resources,
not user-controlled external commands or artifact locations.
