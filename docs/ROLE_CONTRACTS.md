# Governed Role Contracts

Exactly six source-controlled role contracts have distinct schemas, prompts, and validation
policies. All prompts share the code-owned authority boundary, but they are not copies of a generic
agent prompt. Each output uses code-supplied IDs and timestamps and can cite only allow-listed
evidence identifiers.

- **Researcher** turns the bounded question into a falsifiable proposal with primary/null
  hypotheses, variables and metrics, evidence requirements, controls and benchmarks, assumptions,
  periods, exclusions, and failure conditions. It cannot approve, lock, amend, claim execution, or
  issue a verdict.
- **Methodology Auditor** checks causality, temporal leakage/look-ahead, survivorship, controls,
  benchmarks, cost assumptions, regime coverage, preregistration, multiplicity, and amendment need.
  It may request changes but cannot rewrite the proposal, approve execution, or issue a verdict.
- **Statistical Reviewer** evaluates uncertainty, effect direction and practical significance,
  multiplicity, selection, power, resampling, stability, robustness, and assumptions. Every finding
  requires supplied evidence IDs. Narrative numbers and fabricated results are rejected. It cannot
  rerun or alter the engine.
- **Adversarial Reviewer** produces typed challenges covering alternative explanations, hidden
  assumptions, fragility, regimes, data quality, implementation, and falsification. Typed status
  separates demonstrated failures from unresolved concerns; failed claims require supplied
  evidence.
- **Reproducibility Reviewer** reviews code-owned manifest, hash, input, environment,
  reconstruction, completeness, schema, and replay observations. Verified status and verification
  booleans are forbidden unless code explicitly supplied successful reproducibility verification.
- **Tribunal Chair** receives the deterministic eligibility result and validated findings. It may
  explain limitations, evidence, and change conditions, but its verdict and decisive/contradictory
  evidence sets must exactly equal the code-owned result. The final code-owned graph is committed in
  the same transaction.

Prompt, schema, and validation-policy IDs and versions are governed source artifacts. Their
canonical hashes are included in requests and results. Source indentation normalization does not
create an accidental artifact change; a substantive governed prompt or policy edit changes its
hash. Incompatible identities fail closed; there is no mutable remote prompt or provider-supplied
system instruction.
