# Phase 2B Provider Threat Model

Claims, evidence summaries, filenames, metadata, prior reviews, retrieved text, datasets, and model
responses are hostile data. `RoleRequestBuilder` places source-controlled instructions in a system
message and canonical, explicitly labelled untrusted context in a separate user message. Context is
case/revision/constitution bound, deterministically ordered, identity recorded, field/array/Unicode
validated, and constrained by character and approximate-token budgets. Unknown fields, unrelated
case data, fabricated evidence IDs, and cross-case or stale summaries are rejected.

Covered attacks include instructions to ignore the constitution; command/file/tool requests;
fabricated engine runs, evidence, human approval, or verdicts; Chair upgrades; post-amendment stale
results; cross-case/revision/model substitution; prompt/schema/policy hash substitution; malformed,
duplicated, fenced, trailing, non-finite, deeply nested, oversized, confusable, or non-normalized
JSON; refusal/truncation; retry exhaustion; repeated request IDs; replayed results; and observational
changes attempting to alter semantic identity.

The provider object is deliberately missing `CaseStore`, engine, evidence-ledger, filesystem, shell,
SQL, URL, and tool handles. SQL is code-owned and parameterized. The SDK request has no tools.
The official SDK base URL is fixed in code; ambient base-URL configuration cannot select a gateway.
Provider text cannot instantiate trusted receipt types or satisfy engine capability checks. A model
response that is structurally valid remains untrusted advisory data until role policy and case
authority validation succeed.

Credentials enter only from `OPENAI_API_KEY` or an injected source. They are excluded from models,
canonical hashes, durable rows, exports, fixtures, exception detail, and logs. Only an optional
SHA-256 digest of raw output text is retained; raw response content is not stored by this provider.
The official API is still an external confidentiality boundary, so operators must submit only
approved non-sensitive context.

Residual risks include nondeterministic model content, provider availability and cost, official API
retention outside QuantForge's control, and complete local artifact-set replacement by an attacker
who controls the host. Semantic replay proves what QuantForge accepted, not that a later live call
will reproduce it. Live verification is evidence of one bounded run, not numerical evidence,
provider availability assurance, financial advice, or a profitability claim.
