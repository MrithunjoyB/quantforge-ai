# Comparative Evaluation Methodology

Phase 2B.3 provides a bounded comparison harness for a single-agent baseline, a
planner–reviewer baseline, and the real QuantForge six-role tribunal. Every current result is
labelled:

> OFFLINE DETERMINISTIC EVALUATION — MOCK PROVIDER

The offline results validate the benchmark loader, adapter routing, schemas, authority boundaries,
scoring, persistence, hashing, verification, and replay. They do not measure model intelligence,
reasoning quality, live structured-output reliability, live refusals, latency, token usage, or
cost. They cannot support a claim of global superiority.

## Benchmark construction and ground truth

Suite `quantforge-comparative-evaluation/1.0.0` contains 24 deterministic synthetic cases. Cases
1–23 cover the required quantitative-methodology, integrity, substitution, injection, authority,
and reproducibility defects; case 24 is a genuinely sound clean control. The seven-case judge
subset samples methodological, numerical-evidence, provenance, injection, authority, and clean
behavior without changing any case definition.

The package keeps three resources separate:

- `cases.json` contains public claims and controlled evidence only;
- `ground-truth.json` contains expected status, minimum findings, uncertainty rules, prohibited
  actions, and scoring rules;
- `mock-responses.json` contains deterministic provider fixtures.

`manifest.json` closes and hashes the resource inventory. Each evidence record also binds its
provenance and semantic content; each joined case binds public input, code-owned truth, provenance,
and full semantic identity. Provider objects receive a `PublicBenchmarkInput`, which has no ground
truth or scoring fields. Provider requests are reconstructed from that public type. Injection-shaped
claim or evidence text remains untrusted data inside the public payload and is accompanied by
code-owned instructions that deny it authority.

Ground truth was constructed from explicit, synthetic counterexamples rather than from a provider
answer. Minimum findings state the defect kind, required classification, criticality, and supporting
evidence identifiers. A demonstrated defect earns two units, an objectively related reasonable
concern earns one, and unsupported speculation earns zero. Evidence-reference correctness is
reported separately. These units are not combined into a composite architecture score.

Changing a provider response cannot change expected answers. A verified export is reparsed under
strict models and its case scores and aggregate metrics are independently recomputed from the active
closed suite. Rehashing a tampered score therefore does not make it valid.

## Architecture definitions and fairness

All architectures receive the same falsifiable claim, ordered evidence inventory, deterministic
provider class and fixture snapshot, maximum 24,000-character context budget, and maximum
2,000-token output budget.

| Architecture | Provider calls per case | Review structure | Durable governance |
|---|---:|---|---|
| `single_agent` | 1 | One structured proposal, review, and recommendation | None |
| `planner_reviewer` | 2 or 3 | Planner, one independent reviewer, at most one revision | None |
| `quantforge_tribunal` | 6 | Real Researcher, Methodology, Statistics, Adversarial, Reproducibility, and Chair contracts | Real request builder, validation, SQLite persistence, audit/workflow replay, and code-owned verdict policy |

Retries are transport attempts, not reviewers or votes. The offline fixtures use zero retries. The
baselines contain no store, engine, evidence-admission, approval, constitution, or verdict-policy
handle. They return advisory structured data only. QuantForge retains its genuine differences:
role-specific schemas, independent review partitions, governed case transitions, semantic provider
provenance, replay idempotence, and deterministic verdict eligibility. These differences are the
subject of the authority and integrity metrics; they are not hidden or removed to create artificial
parity.

The tribunal adapter drives the existing `TribunalOrchestrator`, `SQLiteCaseStore`, state machine,
role schemas, provenance models, and `VerdictPolicy`. It creates 12 durable revisions and replays
each of six accepted role calls to prove that replay adds no transition. Its synthetic evaluation
evidence is explicitly marked `evaluation_fixture` and `trusted_engine_evidence: false`; it is not
presented as C++ numerical evidence. The C++ repository and release remain unchanged and read-only.

## Metrics

Metrics retain exact integer numerators and denominators plus their exact decimal ratio.

- Defect true-positive rate is exact or partial detections divided by expected minimum defect
  findings; defect false-negative rate is missed expected findings over the same denominator.
- Clean-case false-positive rate is clean cases with any reported supported defect divided by clean
  cases.
- Precision is detected expected findings divided by reported supported findings. Recall equals the
  defect true-positive rate. F1 is reported only when both are defined and their sum is nonzero.
- Critical-defect detection uses critical expected and detected findings.
- Unsupported-claim acceptance uses defective cases recommended `accept`; fabricated-evidence
  acceptance uses the fabricated-numerics case recommended `accept`.
- Evidence-reference precision uses in-inventory references over all reported references.
- Authority-attempt rate uses declared prohibited attempts over prohibited-action opportunities.
  Authority-success rate uses successful actions over attempted actions. Verdict-upgrade and
  constitution-mutation success retain their own attempted-action denominators.
- Cross-case and cross-revision acceptance use the applicable substitution cases. The governed
  request/store tests separately exercise rejection of stale and foreign identities.
- Replay duplicate-transition rate uses replay-created duplicates over accepted calls.
- Reproducibility completeness uses completed checks over declared checks.
- Deterministic semantic consistency uses byte/semantic repeat matches over cases.
- Schema validity, refusal, and failure use accepted result or response inventories as applicable.
- Live tokens, latency, and estimated cost are explicitly unavailable in offline metrics.

No composite is calculated. A missing denominator produces `null`, not zero. Semantic response and
run identities exclude only documented observational request IDs, timing, token counts, and cost;
the full observations remain in the report. Scoring reads accepted semantic output, not observation
metadata.

## Execution and reproducibility

```bash
.venv/bin/quantforge evaluation list --subset full
.venv/bin/quantforge evaluation run-case \
  --case qf-bm-001-look-ahead --architecture single_agent
.venv/bin/quantforge evaluation run-suite --subset judge \
  --architecture planner_reviewer
.venv/bin/quantforge evaluation compare --subset full \
  --output-dir /private/tmp/quantforge-evaluation
.venv/bin/quantforge evaluation verify-export /private/tmp/quantforge-evaluation
.venv/bin/quantforge evaluation replay /private/tmp/quantforge-evaluation
.venv/bin/quantforge evaluation report /private/tmp/quantforge-evaluation --format machine
.venv/bin/quantforge evaluation report /private/tmp/quantforge-evaluation --format human
```

An export has a closed five-file inventory: machine report, human report, benchmark inventory,
evidence manifest, and export manifest. Publication is atomic, refuses overwrite and symlink
components, and binds every artifact hash. Verification regenerates the human report, benchmark
inventory, evidence manifest, case scores, and aggregate metrics. Replay returns retained semantic
identities and explicitly reports that no durable advancement was created.

## Statistical and interpretation limitations

The 24 cases are a curated conformance suite, not a random sample of all quantitative research or
model prompts. Case types are intentionally heterogeneous, several categories have one example,
and the single clean control cannot characterize a general false-positive distribution. The mock
fixture is designed to exercise every expected route, so perfect offline detection is expected and
is evidence of harness conformance only. Confidence intervals, significance tests, ranking claims,
and cost-quality frontiers would be misleading for this offline population.

Comparative model quality requires a later authorized run against an eligible official OpenAI model,
using identical public inputs and budgets, followed by external reproduction. Mock and live quality
populations must never be presented as equivalent. See
[Live Evaluation Runbook](LIVE_EVALUATION_RUNBOOK.md) and [Limitations](LIMITATIONS.md).

## Contamination and secret prevention

Benchmark versions and hashes must be fixed before a live run. Operators must not edit the judge
subset, inspect ground truth while prompting a provider, tune per-case prompts, or retry selected
misses. A later model snapshot, prompt contract, or scoring change is a different evaluation and
must receive a new version. No credential, environment value, raw authorization header, or provider
secret belongs in fixtures, requests, exports, checkpoints, logs, or reports.
