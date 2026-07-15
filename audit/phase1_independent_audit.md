# QuantForge AI Phase 1 Independent Audit

Audit date: 2026-07-15

Original audited commit: `2e9da09f4470a1c50e756a06ab935d90f1beaa7a`

Branch: `main`

Decision: **Passed after repair; Phase 2 may begin within the boundaries below.**

## Executive assessment

The original Phase 1 implementation had a strong typed foundation and a green baseline, but it did not yet prove all of the authority, replay, evidence, and release contracts it claimed. Independent adversarial reproductions found five High and four Medium defect groups. Every High and Medium finding was repaired within `quantforge-ai`, covered by regression tests, and revalidated in a fresh locked environment. No Critical finding remains.

The final implementation is a genuinely code-governed offline tribunal. A single immutable transition table owns the exact workflow order, authorized actors, and audited actions. Strict immutable models and semantic audit replay prevent advanced state from being established through construction, copy, deserialization, helper, restoration, or CLI paths. Provider outputs cannot choose workflow state, validate evidence, or compute verdicts. `VerdictPolicy` is pure and separate from the Chair, which can only explain the exact result and evidence set.

The final clean-environment gate passed 281 tests with 92.39% branch-aware overall coverage and 92% rounded coverage across governance-critical modules against a 90% minimum. Both hashed dependency graphs have no known vulnerabilities. The wheel works outside the source tree, all three demos are byte-deterministic, and the protected C++ repository is unchanged.

## Environment and repository proof

- macOS 26.5.2 build 25F84, arm64; Asia/Kolkata.
- Python 3.12.13; pip 26.1.2; pytest 9.0.3; mypy 1.19.1; Ruff 0.14.14; pip-audit 2.9.0.
- QuantForge began at the expected clean commit. No remote existed or was added. No push, tag, release, amend, or history rewrite occurred.
- Protected engine HEAD before and after pre-commit verification: `9266f317573e90452ca88c7d30196d8b6d6f21a3`.
- Protected `v1.0.0` annotated tag object: `20ac53c5e4b61ae7b431d5bb263f246e35f8d2a2`; peeled target: `2f86b71dbc9f29dbda861942d8afbb10c04b6625`; object type: `tag`.
- Protected tracked diff, staged diff, and untracked inventory were empty before and after.
- Protected ignored inventory remained 16,301 paths with SHA-256 `9f99224e3a34dfd512442f0e0931ca201a896f66265aefa91d2992a09f4e092b`.

## Findings and repairs

### Critical

None.

### High — all repaired

**H-01 — Workflow and authority bypass.** Direct construction could establish an advanced state, an unauthorized role could use an otherwise legal transition, restoration did not require equality with replayed history, and generic advancement could bypass an explicit follow-up disposition. The repair adds full staged case invariants; immutable actor/action/state rules; atomic case-plus-audit transitions; explicit follow-up skip/complete operations; and audit-backed restoration. Regression coverage includes `test_transition_actor_authority_is_enforced`, `test_transition_prerequisites_are_required`, `test_nonapproved_methodology_cannot_reach_human_approval`, `test_follow_up_resolution_is_explicit_state_bound_and_authorized`, `test_direct_state_construction_and_unaudited_restoration_are_rejected`, and the construct/copy bypass cases.

**H-02 — Hash-linked but semantically incomplete audit history.** Cross-case concatenation, complete-prefix ambiguity, rehashed policy input manipulation, and incomplete reconstruction were reproduced. Audit events now retain canonical payloads and enforce one case; exact sequence and IDs; strict actor/action and timestamp rules; payload/event hashes; complete history; domain timestamps; full case reconstruction; ledger-derived policy inputs; and deterministic verdict recomputation. JSONL input rejects truncation, malformed records, valid-prefix/malicious-suffix content, oversize files, and symlinks. Regression coverage includes all deletion/insertion/duplication/reordering/sequence/payload/hash/time/actor/case mutations, rehashed semantic mutations, cross-case append, truncation/suffix, and case/audit mismatch tests.

**H-03 — Incomplete evidence and numerical lineage.** Evidence could be rebound to a foreign case, displayed numerical facts could disagree with hashed content, and source artifacts were not fully verified. Evidence now binds case, experiment, constitution, claim IDs, content, source path, and source digest. Numeric facts exactly match canonical values inside hashed content; units are closed and exact; only validated known evidence/facts can be cited; and source artifacts are bounded, contained, regular, nonsymlinked, and digest-matched. Regression tests cover duplicate IDs, wrong hashes and bindings, unsupported units, fabricated citations, narrative number edge forms, fact mismatch, missing artifacts, symlinks, NaN/infinity/exponents/extreme values, and negative zero.

**H-04 — Claim graph admitted invalid semantics.** Type-invalid edges, cycles, insertion-order-dependent exports, and graph/ledger identity disagreement were reproduced. The repair adds node invariants, a closed edge-type matrix, self-edge/cycle/semantic-duplicate rejection, canonical sorting, final-claim evidence traversal, and exact graph-to-ledger inventory/hash/status/relationship reconciliation. Regression tests cover cycles, every invalid edge family, traceability, canonical order, and ledger mismatch.

**H-05 — Verdict inputs and conservative precedence were incomplete.** A methodology revision and an explicitly unresolved robustness gate could produce a positive result; expected direction was missing; policy evidence was not fully reconciled; and fixture flags could influence rather than merely describe governed results. The policy now makes revisions and unresolved robustness inconclusive, rejects a validated opposite direction, handles all gates conservatively, and carries exact decisive and contradictory evidence. Audit replay derives inputs from reviews and ledger and recomputes eligibility. Chair output must equal the computed verdict and evidence. A bounded exhaustive 1,458-combination test proves deterministic precedence alongside direct tests for all five verdicts and Chair escalation.

### Medium — all repaired

**M-01 — Constitution and amendment semantics.** Proposal/approval/constitution experiment bindings, amendment classification/authority, nested primary rewrites, parent lineage, and chronology were incomplete. All are now strict cross-field invariants, including recursively forbidden primary/null/failure-criterion keys and strictly increasing post-lock amendment timestamps.

**M-02 — Validation and serialization escape edges.** Pydantic construct/copy escape hatches, negative-zero identity, Unicode-equivalent key collisions, in-memory JSON size limits, unsafe path components, and temporary-file handling were hardened. Domain construction and copies revalidate; canonical JSON uses NFC with collision rejection; floats and nonfinite/extreme decimals are rejected; zero has one identity; JSON is byte/depth bounded; symlink components are rejected; and output uses unpredictable same-directory 0600 temporary files with fsync and atomic replacement.

**M-03 — Reproducible development and installed artifact failure.** The development graph lacked a fully hashed lock; pytest 9.0.2 was affected by `PYSEC-2026-1845`; the first clean wheel exposed an `audit → workflow → audit` import cycle; and the returned bundle inventory omitted its manifest digest. The repair adds a complete hashed development lock, pins build tools, upgrades pytest to 9.0.3, lazily exposes `StateMachine` to break the cycle, hashes the manifest, and excludes repository audit reports from distributions. Wheel, sdist, metadata, contents, entry point, CLI, replay, and `pip check` now pass outside the repository.

**M-04 — Documentation described intent more strongly than enforcement.** README, architecture, governance, constitution, evidence, verdict, security, threat model, ADR 0002, contribution, and changelog content were reconciled with actual code and limitations. Commands and local links pass. The three official Agents SDK links resolve.

### Low and Informational — accepted boundaries

**L-01 — No external audit anchor.** The local chain detects partial/accidental tampering, but it is not signed or externally anchored. A party controlling the entire bundle can replace and rehash it. This is explicit and nonblocking for a single-user offline foundation; Phase 2 should add a signature or append-only external anchor.

**I-01 — Deliberately absent capabilities.** Phase 1 has no live provider, market data, real engine adapter, UI, RAG, database, broker, order submission, network execution, or profitability claim.

**I-02 — Amendment admission is not yet a durable workflow.** Amendment models and chain invariants exist; an audited persisted admission path is deferred and must not silently merge exploratory work into the locked primary result.

**I-03 — Random-order plugin unavailable.** No dependency was added solely for auditing. The complete 281-test suite passed again with test files listed in reverse order.

## Model-risk and security assessment

All five verdict classes are reachable. The policy truth table covers methodology rejection/revision, incomplete experiments, invalid or pending evidence, inference failure, hypothesis direction, practical significance, robustness, cost, parameter/regime stability, concentration, reproducibility, critical limitations, and contradictory evidence. Missing or unresolved critical gates cannot strengthen a verdict. The fragile fixture contains meaningful structured contradictory evidence, and its verdict follows policy rather than its filename.

There is no live prompt-injection surface. A future provider remains untrusted: structured output must be revalidated into strict QuantForge models, while code retains state, approval, evidence-validation, and verdict authority. Package source contains no network client, shell/subprocess authority, broker path, order submission, or live trading. Malicious JSON, duplicate keys, deep/oversized data, Unicode ambiguity, path/symlink traversal, artifact substitution, identifier spoofing, unstructured numerical claims, and semantic audit tampering have direct negative tests. Tests require neither a network nor an API key.

## Exact validation results

- `PYTHON=/private/tmp/quantforge-dev-audit-20260715/bin/python ./scripts/quality.sh`: format pass; Ruff pass; strict mypy pass; **281 passed**; **92.39%** overall branch-aware coverage; governance-critical aggregate **92% rounded**, minimum 90%; no skips; secret scan pass; wheel and sdist build pass.
- Complete suite in reverse file order: **281 passed in 16.17s**.
- Fresh Python 3.12 development environment installed via `pip install --require-hashes -r requirements-dev.lock`: pass.
- Runtime and development `pip-audit`: **No known vulnerabilities found** for both.
- Final wheel SHA-256: `99c41e100ba810974a6130bef400251f761620cd16794cde260b045e36d68566`.
- Final sdist SHA-256: `2fe638c66125751bd118fedab26e46198f6b161dc47c1ecddeb87b4ffe263b91`.
- Installed final wheel outside the source tree: import pass; CLI entry point pass; provisional demo pass; case validation pass; 12-event semantic audit verification pass; `pip check` reports no broken requirements.
- Distribution hygiene: license and notice present; no caches, environments, repository audit reports, local absolute paths, secrets, or unwanted build outputs.
- Secret scan: `no known credential patterns found`.
- Documentation links: local and official OpenAI links pass.

## Determinism proof

Each scenario was exported twice in the locked clean environment. `diff -rq` found zero differences across 30 file comparisons (three scenarios × two runs × five files). Stable verdicts are `PROVISIONALLY_SUPPORTED`, `FRAGILE`, and `INCONCLUSIVE`.

| Scenario | audit.jsonl | manifest | case.json | graph | ledger |
|---|---|---|---|---|---|
| provisional | `04a7eb1fad1b…` | `ba2940d86ed3…` | `8331c4d9d743…` | `427de4e0e6c9…` | `5d81de034095…` |
| fragile | `b2dff48e4104…` | `69c583816713…` | `b4229fdd0e47…` | `f921df1ffcac…` | `4a7c6a180a27…` |
| inconclusive | `a6e3aa632991…` | `61a928cff2d7…` | `b4cc9a45e786…` | `364fdd3af2d1…` | `f7bf27d7a71b…` |

The machine-readable report contains the complete hashes.

## OpenAI boundary

ADR 0002 is compatible with current official Agents SDK documentation for agent construction, typed `output_type` structured outputs, and deterministic code orchestration. Phase 2 may add a provider-neutral adapter, but every response must be revalidated before domain admission. A provider must never own workflow state, evidence truth, constitution identity, human approval, verdict policy, or Chair escalation. No live OpenAI integration or dependency was added in this audit.

Official references:

- https://openai.github.io/openai-agents-python/quickstart/
- https://openai.github.io/openai-agents-python/agents/#output-types
- https://openai.github.io/openai-agents-python/multi_agent/#orchestrating-via-code

## Remaining limitations

- Audit hashes are not signed or externally anchored.
- All observations are synthetic fixtures and support no profitability or empirical performance conclusion.
- The protected C++ engine remains deliberately unintegrated.
- No live provider, retrieval, persistence, UI, network, broker, or execution layer exists.
- Persisted audited amendment admission is deferred.
- The verified interpreter/platform is Python 3.12.13 on macOS arm64; declared support is Python 3.12 or newer.

## Phase 2 boundaries

Phase 2 may begin if it preserves these controls:

1. Keep the C++ adapter read-only and bind binary, configuration, inputs, outputs, schemas, and manifests by digest.
2. Treat engine, provider, retrieval, and user artifacts as hostile until strict schema, provenance, size, path, and digest validation passes.
3. Preserve code-owned transitions, explicit human approval, the locked constitution, evidence ledger, typed graph, semantic audit replay, and pure verdict policy.
4. Use structured provider output only for proposals and reviews; grant no filesystem, shell, workflow, validation, or verdict authority.
5. Add external audit anchoring and explicit audited amendment admission before durable multi-user operation.
6. Do not add broker connectivity, order submission, live trading, or profitability claims.

## Final decision

**QUANTFORGE AI PHASE 1 INDEPENDENT AUDIT PASSED — READY FOR PHASE 2**
