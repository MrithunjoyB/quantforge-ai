# ADR 0001: Code-driven sequential tribunal

Status: accepted

## Decision

Use a single deterministic state machine and pure verdict policy. Roles return typed findings; they
do not select routing or verdicts.

## Rationale

Scientific preregistration and human approval require predictable control flow. Free-form handoffs
would make bypass and replay behavior harder to prove. Code-owned orchestration keeps authority,
cost, timing, and state behavior inspectable and testable.

## Consequences

Adding a role or state requires a versioned governance change. Optional follow-up still appears in
the sequence and needs an explicit audited disposition.
