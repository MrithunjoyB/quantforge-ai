# Phase 2B.3 Requirement Map

| Requirement | Implementation | Primary verification |
|---|---|---|
| 24 versioned cases and clean control | `evaluation/benchmarks/v1`, closed resource manifest, strict suite models | `test_evaluation_suite.py`, `test_evaluation_model_invariants.py` |
| Code-owned truth without prompt leakage | Separate public, truth, and mock resources; provider receives `PublicBenchmarkInput` only | `test_provider_request_structurally_excludes_ground_truth_and_scoring` |
| Fair single-agent baseline | One advisory structured request; no governance handle | `test_baselines_have_exact_fair_call_structures_and_no_governance_state` |
| Fair planner–reviewer baseline | Planner, one independent reviewer, at most one revision; zero retry-votes | Same adapter test and full-suite call inventory |
| Real QuantForge tribunal | Existing orchestrator, role contracts, schemas, SQLite store, workflow, provenance, replay, and verdict policy | `test_real_tribunal_adapter_uses_six_governed_calls_and_twelve_transitions` |
| Component scoring | Exact case scorer and aggregate metrics with raw numerators/denominators; no composite | `test_evaluation_scoring.py`, full-suite test |
| Deterministic repeat evidence | Every architecture/case pair executes twice; observations excluded from semantic identity | full-suite and observational-metadata tests |
| Closed export, verification, replay | Atomic five-file export; independent score/metric/report regeneration | `test_evaluation_export.py`, CLI test |
| Tamper and substitution resistance | Closed benchmark/report hashes, strict schemas, case/revision/evidence binding | malicious evaluation tests plus existing governed-request/storage regressions |
| Authority isolation | Baselines have no direct handles; tribunal provider remains advisory; all successes code-owned false | adapter tests and existing role authority regressions |
| Live-ready controls without calls | Exact plan, model/call/cost approvals, six-call receipt, hard budget, namespaced checkpoint, mode separation | `test_live_evaluation_controls.py` |
| Critical coverage | Entire `src/quantforge/evaluation/` namespace added to the 90% branch-aware gate | `test_critical_coverage_command_fails_for_omitted_boundary_paths` |
| Package and CLI | Package resources plus list/run/compare/export/verify/replay/report/live-plan commands | packaging contract and evaluation CLI tests |
| Interpretation limits | Methodology, runbook, README, architecture, and limitations documentation | repository policy, link, citation, and package gates |

The PR description should reproduce this map with exact commit and remote-check identities. This map
does not replace evidence from a full local or remote gate run.
