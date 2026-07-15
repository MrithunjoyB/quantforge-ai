# Support Policy

QuantForge AI is an open-source research-governance project maintained on a best-effort basis. No
service-level agreement, operational monitoring, production support, investment advice, or support
for live-trading use is offered.

## Supported scope

After publication, support covers reproducible defects in the latest `0.1.x` source and packaged
artifacts, using Python 3.12 or newer and synthetic inputs that can be shared publicly. The Phase 1
scope is offline: real providers, market data, the protected C++ engine, persistence, brokers, and
execution systems are unsupported.

For a normal defect or documentation question, open a GitHub issue after the repository is
published. Include the exact QuantForge version and commit, Python version, operating system, command,
minimal synthetic reproduction, expected result, and actual result. Remove credentials, private
data, proprietary market data, and local absolute paths.

Security vulnerabilities must follow [SECURITY.md](SECURITY.md), not a public support issue. Conduct
concerns must follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

Requests that weaken evidence, audit, schema, deterministic, coverage, or verdict controls will not
be accepted merely for convenience. Proposed capability expansions belong in a design issue and must
preserve the boundaries in [Governance](docs/GOVERNANCE.md) and the
[Security Model](docs/SECURITY_MODEL.md).
