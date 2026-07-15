# ADR 0002: Provider-neutral Phase 1 and future OpenAI Agents boundary

Status: accepted for Phase 1

Verified: 2026-07-15 against public OpenAI Agents SDK documentation.

## Verified assumptions

The official Python package is documented as `openai-agents`. The current public interface describes
`Agent`, `Runner.run`, and typed `output_type`; passing an output type requests structured output and
the SDK validates JSON against that type. Official orchestration guidance states that code-driven
orchestration is more deterministic and predictable than LLM-selected routing.

Sources:

- https://openai.github.io/openai-agents-python/quickstart/
- https://openai.github.io/openai-agents-python/agents/#output-types
- https://openai.github.io/openai-agents-python/multi_agent/#orchestrating-via-code

## Decision

Do not install or import the SDK in Phase 1. Define `RoleProvider` using domain return types and ship
only `MockRoleProvider`. A future adapter may use structured SDK output, but must independently parse
and validate the returned domain schema before state admission. It may expose no shell, broker,
unrestricted filesystem, or verdict-selection tool.

The global developer-docs connector could not be installed under the workspace security boundary,
so these assumptions are dated and linked rather than encoded as an SDK dependency. The future
implementation must re-verify current package/API details and pin its dependency before use.
