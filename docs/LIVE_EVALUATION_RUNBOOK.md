# Future Live Evaluation Runbook

Phase 2B.3 prepares a fail-closed live evaluation control plane but does not make or authorize a
live call. Live evaluation is disabled by default. The only permitted future transport is the
existing official `OpenAIStructuredRoleProvider` using `https://api.openai.com/v1`; no router,
gateway, fallback provider, tools, or response storage is permitted.

The existing separate six-call verification in [OpenAI Provider Runbook](OPENAI_PROVIDER_RUNBOOK.md)
must succeed first for the exact operator-selected model. Its receipt must retain status `verified`,
provider `openai`, model identity, exactly six calls, and all six governed semantic hashes. Offline
success is not a substitute.

## Plan before authorization

Generate a plan without credentials or network access:

```bash
.venv/bin/quantforge evaluation live-plan \
  --subset judge \
  --architecture single_agent \
  --architecture planner_reviewer \
  --architecture quantforge_tribunal \
  --model '<exact-operator-selected-model>' \
  --maximum-context-characters 24000 \
  --maximum-output-tokens 2000 \
  --input-price-per-million-usd '<reviewed-current-price>' \
  --output-price-per-million-usd '<reviewed-current-price>'
```

The machine-readable plan binds the suite hash, subset, case and architecture counts, maximum calls,
model, budgets, price assumptions, maximum estimated cost, and plan SHA-256. Worst-case calls per
case are one for single-agent, three for planner–reviewer, and six for QuantForge. The seven-case
judge subset therefore caps all three at 70 calls; the 24-case full suite caps them at 240. The
input-token estimate uses four tokens per bounded context character—the maximum UTF-8 byte width—
rather than an optimistic characters-per-token average, then adds the output-token bound. Provider
billing remains authoritative.

## Required authorization controls

An activation implementation must call `authorize_live_plan` before transport and satisfy all of
these exact checks:

1. `QUANTFORGE_LIVE_EVALUATION=1` is explicitly set for this run.
2. `OPENAI_API_KEY` is available only from the approved environment or secret store.
3. The approved plan SHA-256 exactly matches the printed plan.
4. The approved call budget covers, but never silently expands, the plan maximum.
5. The approved cost cap covers the conservative plan estimate.
6. The six-call verification receipt matches the exact model and six governed roles.
7. Provider retries remain zero; a hidden transport retry would invalidate call and cost ceilings.

`LiveCallBudget.consume()` fails before call `N+1`; `reserve_case()` fails unless the remaining
budget can cover the next complete case. This prevents starting a case that could be left partially
charged solely because the approved budget was exhausted.

Phase 2B.3 deliberately does not expose a command that sends the planned calls. Activating transport
requires a separately reviewed change that reuses the existing official provider and demonstrates
the same schema, authority, provenance, failure-atomicity, and secret-redaction gates for all three
architectures. That change must not add a new external provider API. Until it exists and the
six-call receipt passes, report live benchmarking as not executed.

## Provenance, failure, and resumption

Every future accepted call must retain semantic provider/model/prompt/schema/request/output
identities separately from request IDs, timestamps, latency, usage, retry attempts, and cost. Failed
calls must retain sanitized failure provenance without advancing a durable case. No raw response or
credential may enter a report.

Live checkpoints use namespace `live_openai`, bind the exact plan hash, retain completed
architecture/case results and calls consumed, and reject duplicate completed pairs. Resume must load
that checkpoint, skip completed pairs, reserve the complete next case, and continue within the same
call and cost approvals. An offline checkpoint or different plan cannot be reused. Save checkpoints
atomically after a completed case; do not charge or mark an incomplete case as complete.

Live output is inherently nondeterministic. Preserve full observations, but compare semantic output
only under a declared model and prompt snapshot. Never combine mock and live quality metrics into a
single population: `require_same_result_mode` rejects that comparison. Report mock conformance and
live model quality in separate sections.

## Stop conditions

Stop without fallback on an absent flag, mismatched receipt or model, inadequate call/cost approval,
budget exhaustion, authentication failure, timeout, refusal, truncation, malformed output, schema
failure, authority violation, stale checkpoint, or any attempted non-OpenAI endpoint. Rotate the key
and discard potentially exposed artifacts if a secret appears in output. A partial or failed live
run is not evidence of comparative quality.
