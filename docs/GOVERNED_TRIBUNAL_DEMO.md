# Offline governed tribunal demonstration

Every artifact produced by this surface is part of an artifact set labeled:

> OFFLINE GOVERNED DEMONSTRATION — MOCK PROVIDER

The flagship case tests a deliberately attractive claim: a frozen causal monthly equal-weight
policy appears to outperform `SYN_BENCH` after declared costs and is claimed to be statistically
reliable and robust. The trusted C++ release reports a large point estimate, but the corrected
inference, return interval, drawdown, loss probability, concentration, and regime findings do not
support that stronger claim. The code-owned outcome is `INCONCLUSIVE`.

This is the intended result, not a failed presentation. It demonstrates why governance must be able
to reject a persuasive return narrative.

## Exact commands

Python dependencies and QuantForge must first be installed from the reviewed locks. Build the
protected C++ `v1.0.0` target in a directory outside its repository. The example below uses the
already reviewed executable and keeps every run output outside both repositories:

```bash
QF_CPP_REPOSITORY=/absolute/path/to/cpp-event-driven-backtester
QF_CPP_EXECUTABLE=/absolute/outside/build/directory/quant_cli
QF_CPP_WORK_ROOT=/private/tmp
QF_CPP_EXECUTABLE_SHA256="$(.venv/bin/python -c \
  'import hashlib, pathlib, sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())' \
  "${QF_CPP_EXECUTABLE}")"

.venv/bin/quantforge demo run \
  --repository "${QF_CPP_REPOSITORY}" \
  --executable "${QF_CPP_EXECUTABLE}" \
  --expected-executable-sha256 "${QF_CPP_EXECUTABLE_SHA256}" \
  --work-root "${QF_CPP_WORK_ROOT}" \
  --output-dir /private/tmp/quantforge-governed-tribunal

.venv/bin/quantforge demo verify /private/tmp/quantforge-governed-tribunal
```

Use an existing non-symlink `/tmp` path on Linux. The output directory must not already exist; the
demo assembles it privately, verifies it, and publishes it with one atomic rename. Once the C++
executable is built, one run usually takes approximately ten to thirty seconds on a developer
machine. CI runs wheel and source-distribution executions separately.

## Lifecycle actually exercised

The command executes the real governed path:

```text
claim -> Researcher -> Methodology Auditor -> simulated human approval
      -> immutable constitution -> trusted C++ execute-and-admit
      -> Statistical Reviewer -> Adversarial Reviewer -> optional follow-up disposition
      -> code-owned reconstruction -> Reproducibility Reviewer
      -> deterministic verdict eligibility -> Tribunal Chair
      -> durable export -> independent package verification
```

The provider request builder creates role-specific, revision-bound contexts. Each mock response is
validated against its governed prompt, schema, validation policy, provider identity, request
identity, evidence references, and allowed transition. Every accepted role transaction is
immediately replayed: the store returns the accepted result without a second transition or provider
record.

The explicit simulated approval is recorded before the immutable constitution and before numerical
execution. It is a demonstration approval, not an assertion that a real person approved an
investment or deployment.

## What is real

- The twelve workflow transitions and revision-checked SQLite transactions.
- Role-specific contracts, request construction, strict validation, and semantic/observational
  provider provenance.
- Explicit simulated human approval and constitution/amendment identities.
- The same-process trusted C++ `v1.0.0` execute-and-admit capability.
- Release, repository, executable, configuration, input, validator, invocation, output, and numeric
  fact verification.
- Source-artifact-bound evidence objects and reviewer references to allow-listed fact IDs.
- `VerdictPolicy` computation, durable export, audit replay, claim-graph verification, and
  independent reconstruction.

## What is deterministic mock output

The differentiated prose and structured advisory judgments from the Researcher, Methodology
Auditor, Statistical Reviewer, Adversarial Reviewer, Reproducibility Reviewer, and Tribunal Chair
are package-owned deterministic fixture output. The mock has no network, engine, evidence,
approval, workflow-transition, or verdict authority. It demonstrates that the Phase 2B provider
boundary works; it does not demonstrate model intelligence.

The verdict is computed before the Chair request. The Chair receives the eligibility object and can
only return a schema-valid explanation whose verdict matches it. Different explanation wording
changes the Chair response identity, but cannot change the stored eligibility or decisive evidence.

## Artifacts and interpretation

The output directory contains:

- `case-spec.json`: falsifiable claim, strategy, controls, assumptions, criteria, failure gates, and
  expected evidence inventory;
- `tribunal-result.json`: complete case, timeline, role results, prompt/schema/policy/provider
  provenance, engine/evidence identities, verdict, replay status, and semantic identities;
- `tribunal-report.md`: judge- and reviewer-oriented case report;
- `evidence-manifest.json`: presentation evidence and capture order;
- `case-package/`: independently reconstructable durable export;
- `demo-manifest.json`: closed outer inventory and SHA-256 binding for every other artifact.

`quantforge demo verify` rejects missing, extra, stale, substituted, symlinked, or hash-mismatched
artifacts, verifies the nested case package, reconstructs the final case, and recomputes the stable
demonstration identity. Trusted execution times and permitted raw JSON observations may differ
between runs. Those observations remain tamper-evident but do not affect the stable governed
semantic identity.

`INCONCLUSIVE` means the attractive point estimate is insufficient to establish the claim as
written. It is not a prediction of future loss, a recommendation, or permission to trade.

## Pending work and limitations

No OpenAI, ZenMux, Claude, Kimi, broker, market-data, paper-trading, or live-trading call occurs.
A separately authorized live OpenAI contract verification remains pending before making any claim
about live-model behavior. Synthetic C++ evidence validates the architecture and its research
controls, not empirical profitability or future performance. Local hash chains are not externally
signed or independently timestamped.
