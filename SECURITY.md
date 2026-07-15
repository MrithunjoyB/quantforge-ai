# Security policy

Do not report sensitive vulnerabilities in public issues. Report them privately to the repository
maintainer with reproduction steps, affected versions, and impact. Do not include real credentials
or private data.

Phase 1 has no network provider, broker, market-data adapter, arbitrary command tool, or unrestricted
filesystem role capability. Treat serialized cases, evidence, audit logs, artifact paths, and future
model output as hostile. See [Security Model](docs/SECURITY_MODEL.md) and
[Threat Model](docs/THREAT_MODEL.md).

No security support claim is made for uncommitted local modifications or future integrations that
bypass the documented adapters.
