# Contributing

QuantForge changes must preserve scientific and governance controls. Open a design issue before
changing workflow states, schema or policy versions, canonical serialization, evidence requirements,
audit identity, role authority, or verdict policy. New behavior requires tests for success,
rejection, tampering, malicious inputs, and boundary cases.

## Development environment

Use Python 3.12 or newer. Install only the reviewed hash lock, then install the project without
dependency resolution:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
.venv/bin/python -m pip install -e . --no-deps --no-build-isolation
scripts/quality.sh
```

To regenerate locks, use Python 3.12 in a clean environment with the pinned `pip-tools` from the
current development lock:

```bash
.venv/bin/python -m piptools compile --generate-hashes --strip-extras \
  --output-file requirements.lock requirements.in
.venv/bin/python -m piptools compile --allow-unsafe --generate-hashes --strip-extras \
  --output-file requirements-dev.lock requirements-dev.in
```

Review every version, marker, origin comment, and hash change. Then reinstall both locks in fresh
environments, run runtime and development dependency audits, and run the complete quality gate.
Never hand-edit a distribution hash to conceal a resolver change.

## Change requirements

- Reproduce failures, repair their root cause, add a regression test, and rerun affected gates.
- Keep direct dependencies exactly pinned and transitive distributions hash-locked.
- Preserve strict schemas, deterministic outputs, governance-critical coverage, and conservative
  verdict limits.
- Use synthetic, redistributable fixtures. Do not commit credentials, private data, local paths,
  environments, caches, IDE state, or generated release output.
- Do not modify the protected sibling C++ repository or add broker, order, or live-trading behavior.
- Keep documentation and release notes accurate; never claim profitability or production readiness.

Pull requests should be focused, explain governance/security impact, identify new dependencies and
their licenses, and include exact validation results. All commits remain subject to the
[Code of Conduct](CODE_OF_CONDUCT.md).

By contributing, you agree that your contribution is licensed under Apache License 2.0.
