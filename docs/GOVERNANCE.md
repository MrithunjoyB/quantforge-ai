# Governance

The six governed roles have narrow authority:

- Researcher proposes a falsifiable experiment before results are visible.
- Methodology Auditor reviews causality, leakage, parity, execution, selection risk, and evaluability.
- Statistical Reviewer assesses corrected inference, effect direction, practical meaning, and sample
  limitations using evidence references.
- Adversarial Reviewer requests and evaluates bounded falsification challenges.
- Reproducibility Reviewer verifies identity, lineage, manifests, hashes, and reconstruction.
- Tribunal Chair explains the policy result and cannot select, change, or strengthen it.

Human approval binds the exact proposal hash before a constitution may lock. No role can mutate the
locked primary protocol, invent facts, execute commands, trade, bypass state, or cite missing
evidence. Follow-up is entered as a state and can be skipped only with an explicit audited reason.

The role matrix and the workflow transition table reject prohibited actors and actions independently
of provider prompts. The same immutable table governs live transitions and audit replay. A role may
return a typed proposal or review, but only the state machine can admit it; the Researcher and Chair
cannot advance any transition outside their one assigned boundary.

The code-owned tribunal orchestrator receives its provider through dependency injection and retains
each complete `ProviderResult`. Provider/model/prompt/schema/validation/output identities are
semantic and participate in verdict inputs. Request IDs, timing, usage, retries, and transport are
observational and cannot change eligibility by themselves. Providers receive no workflow object,
filesystem, shell, engine, evidence-admission, graph, verdict-policy, broker, order, or trading
authority.
