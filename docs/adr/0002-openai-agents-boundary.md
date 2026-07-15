# ADR 0002: Provider-neutral Phase 1 and future OpenAI Agents boundary

Status: accepted for Phase 1

Verified: 2026-07-15 against public OpenAI Agents SDK documentation.

## Verified assumptions

The official Python package is documented as `openai-agents`. The current public interface describes
`Agent`, `Runner.run`, and typed `output_type`; passing an output type requests Structured Outputs.
Official orchestration guidance states that code-driven orchestration is more deterministic and
predictable than LLM-selected routing.

Sources:

- https://openai.github.io/openai-agents-python/quickstart/
- https://openai.github.io/openai-agents-python/agents/#output-types
- https://openai.github.io/openai-agents-python/multi_agent/#orchestrating-via-code

## Decision

Do not install or import the SDK in Phase 1. Define `RoleProvider` using domain return types and ship
only `MockRoleProvider`. A future adapter may use structured SDK output, but must independently parse
and validate the returned domain schema before state admission. It may expose no shell, broker,
unrestricted filesystem, or verdict-selection tool.

These assumptions were re-verified from the linked official OpenAI Agents SDK documentation during
the independent Phase 1 audit. The SDK remains absent from runtime and development dependencies. A
future adapter must re-verify current API details, pin the complete dependency graph, and treat SDK
structured output as untrusted until the QuantForge domain model independently validates it.
