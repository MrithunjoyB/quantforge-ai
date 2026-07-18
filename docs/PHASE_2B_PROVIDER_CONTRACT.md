# Phase 2B Structured Provider Contract

Phase 2B adds one optional official OpenAI transport to the existing tribunal. It is disabled by
default. `CaseStore`, SQLite, canonical JSON, the injected `TribunalOrchestrator`, the state machine,
the trusted C++ adapter, evidence admission, and `VerdictPolicy` retain their Phase 2A authority.
The provider receives a bounded request and returns advisory typed data; it has no store, engine,
filesystem, shell, tool, approval, constitution, evidence, or verdict capability.

The bounded transaction is:

1. reconstruct the exact case revision and build a role-minimal request in code;
2. invoke one dependency-injected provider with bounded timeout, output, and retries;
3. independently validate raw JSON, the exact role schema, identities, evidence allow-lists, and
   role policy;
4. persist the attempt group and accepted `ProviderResult` atomically with the eligible workflow
   event; and
5. for the final Chair transition, atomically anchor the code-owned final claim graph too.

Any failure records observations without advancing workflow. A partial unique SQLite index permits
only one accepted result for a role/action at a case revision, so retries cannot become reviewer
votes. Accepted outputs can be replayed semantically without replaying observations or transitions.

## Structured output and identity

The official Python SDK is pinned and the implementation uses `client.responses.parse` with a
source-controlled strict Pydantic model, `tools=[]`, disabled truncation, no remote prompt, and
`store=False`. The SDK client is explicitly pinned to `https://api.openai.com/v1`, so an ambient
`OPENAI_BASE_URL` cannot redirect calls to a gateway. The operator must select OpenAI mode and
provide a model identifier; there is no model default and no compatibility endpoint. The returned
model snapshot must match the configured identifier before orchestration accepts it.

Raw output is independently parsed before trusting the SDK-parsed object. The parser rejects size
or depth excess, duplicate keys, floats, NaN/Infinity, trailing content, Markdown fences,
non-object roots, unknown/missing fields, invalid types, non-NFC text, forbidden Unicode code
points, and schema drift. Structural validity is not authenticity and never admits evidence.

Semantic provenance includes the provider contract, provider, requested and returned model,
endpoint class, SDK version, role, prompt/schema/policy identities, versions and hashes, request and
output hashes, optional raw-response digest, retry policy, every context-item identity, case and
revision, constitution and amendment-chain identities, and supplied evidence IDs. Observational
provenance includes request/response IDs, timestamps, latency, usage, retry count, transport status,
rate-limit fields, refusal/truncation flags, and every attempt. Observations are excluded from the
semantic hash and cannot affect replay, evidence, workflow, or verdict eligibility.
The raw-response digest authenticates retained transport provenance but is likewise excluded from
the accepted semantic identity: whitespace-only JSON transport changes cannot become a new vote.
Failed invocations retain the same provider, model, endpoint, SDK, prompt, schema, policy, request,
role-context, case, constitution, amendment, evidence, and retry-policy identities as accepted
calls, together with every bounded attempt observation.

## Failure and retry policy

Failures are classified as transport, authentication, rate limit, timeout, provider refusal,
safety refusal, truncation, malformed structured output, schema validation, semantic policy, or
unsupported model capability. Transport, timeout, and rate limit outcomes alone are retryable,
using a fixed bounded schedule and at most two retries. The official SDK's own retries are disabled.
Refusal, truncation, schema, authentication, capability, and policy failures are terminal. Error
messages are sanitized; response bodies and credentials are not persisted or logged.

Provider output is not numerical evidence. The provider cannot execute the C++ engine, admit
evidence, create authenticity or admission receipts, record human approval, lock or amend a
constitution, determine verdict eligibility, or upgrade a verdict. No trading, broker, order,
market-data, portfolio, financial-advice, or profitability capability exists.

The transport contract follows OpenAI's official
[Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs) and
the pinned official
[OpenAI Python SDK v2.46.0 release](https://github.com/openai/openai-python/releases/tag/v2.46.0).
