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

The `RoleAuthority` matrix rejects prohibited actions independently of provider prompts. The state
machine rejects every transition not present in the single locked sequence.
