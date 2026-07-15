# ADR 0003: Canonical JSON and explicit decimals

Status: accepted

## Decision

Canonical identity uses recursively sorted compact JSON, UTF-8, UTC microsecond timestamps, explicit
decimal strings, and SHA-256. Floats are forbidden from identity and policy serialization.

## Rationale

JSON number parsing and binary floating-point formatting can vary across languages and runtimes.
Explicit decimals make money, rates, facts, hashes, and policy decisions reproducible.
