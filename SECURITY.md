# Security Policy

## Supported versions

Before public release, only the exact committed `v0.1.0` candidate is assessed. After publication,
the latest `0.1.x` release receives best-effort security fixes. Uncommitted modifications, forks, and
future integrations that bypass documented adapters are not covered.

## Private reporting

Do not disclose a suspected vulnerability in a public issue. Before the GitHub repository exists,
contact the maintainer through the private channel used to provide this candidate. After publication,
use GitHub private vulnerability reporting for the repository. Include:

- affected version and exact commit;
- minimal synthetic reproduction and prerequisites;
- expected versus observed security boundary;
- impact, exploitability, and whether disclosure has occurred;
- suggested remediation, if known.

Never include a real credential, private market data, personal data, or proprietary artifact. The
maintainer will acknowledge the report, reproduce it, assess severity, coordinate a repair and
regression test, and agree on disclosure timing. No bounty or response-time guarantee is offered.

## Current threat boundary

OpenAI provider mode is optional, disabled by default, strictly structured, and has no tools, store,
engine, evidence-admission, filesystem, shell, SQL, approval, constitution, or verdict authority.
Credentials come only from the environment or an injected source and are excluded from durable and
semantic artifacts. There is no broker, market-data adapter, arbitrary command tool, unrestricted
role filesystem access, or live trading. Serialized cases, evidence, audit logs, artifact paths,
archives, and model output are hostile input. See the
[Security Model](docs/SECURITY_MODEL.md) and [Threat Model](docs/THREAT_MODEL.md).

The local audit chain detects partial or accidental tampering but is not signed or externally
anchored. A party controlling the complete artifact set can replace and rehash it; this is an explicit
Phase 2 limitation, not a security guarantee.
