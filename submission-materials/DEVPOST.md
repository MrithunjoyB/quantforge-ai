# Devpost drafts

These are editable source drafts. Nothing in this file has been posted automatically.

## Project name

QuantForge

## Descriptive subtitle

A Research Tribunal for Quantitative Claims

## Short tagline

A research tribunal that tests whether quantitative claims deserve trust.

## Overview (100–150 words)

Backtests can look persuasive even when their evidence is weak. QuantForge turns a quantitative
claim into a governed experiment: a Researcher proposes the protocol, a Methodology Reviewer
challenges it, a human approves a locked constitution, and a deterministic C++ engine produces the
numerical evidence. Statistical, adversarial, and reproducibility reviews follow, but code—not the
model—validates evidence and computes the verdict. In the flagship synthetic demonstration, a
185.43% return is accompanied by a −42.47% drawdown, a corrected p-value near 0.309, and a 25.2%
bootstrap loss probability. The final verdict is therefore INCONCLUSIVE. The project includes a
six-role tribunal, strict structured OpenAI integration, durable audit and replay, a deterministic
offline demonstration, and a 24-case comparative benchmark. The submission uses the mock provider;
funded live OpenAI verification remains pending.

## Full project description

### The problem

A strong backtest is easy to present and hard to audit. The return chart may be correct while the
research claim is still unreliable because the experiment used too many candidates, a weak
benchmark, incomplete transaction costs, unstable parameters, or evidence that cannot be
reconstructed. Once the result has become a polished narrative, those choices are easy to overlook.

I built QuantForge to preserve the research argument, not just its most attractive number. It treats
a claim as a governed case with an approved protocol, evidence identities, explicit objections, a
durable audit trail, and a verdict whose strength is limited by code.

### How a claim becomes a governed experiment

The workflow begins with a falsifiable research claim. A Researcher proposes the experiment and a
Methodology Reviewer checks causality, leakage, benchmark parity, execution assumptions, and
multiple testing. A human approval is required before QuantForge locks the experiment constitution.
Only then can the narrow C++ adapter run the approved synthetic fixture and admit its evidence.

Statistical, Adversarial, and Reproducibility Reviewers examine the admitted evidence. Their outputs
must pass role-specific schemas and may reference only validated facts. QuantForge reconstructs the
case, verifies the claim graph and evidence lineage, and passes deterministic inputs to
`VerdictPolicy`. The Chair receives the already computed outcome and may explain it, but cannot make
it stronger.

This creates a clear separation of responsibility. The model can propose, criticize, and explain.
The C++ engine owns numerical execution. QuantForge code owns state, evidence admission, approval,
the constitution, and verdict authority. The model cannot create evidence or choose the verdict.

### Flagship demonstration

The flagship case is deliberately tempting. The frozen monthly equal-weight policy reports a
185.43% total return and 100.97% excess return over the synthetic benchmark after declared costs.
That point estimate is real output from the protected deterministic C++ fixture, but it is not the
whole case.

The same admitted evidence reports a −42.47% maximum drawdown, a corrected reality-check p-value of
0.308691, a bootstrap return interval that crosses zero, a 25.2% probability of loss, and material
concentration and regime objections. Reproducibility passes, but statistical reliability and
robustness do not. The code-owned verdict is INCONCLUSIVE.

I consider that a successful demonstration. QuantForge did not turn an attractive return into an
unsupported claim. It kept the useful result, the contradictory evidence, and the limit on what the
experiment can honestly establish.

### What is included

- a deterministic C++ numerical engine with project-owned synthetic data;
- strict claim, constitution, evidence, review, workflow, and verdict models;
- a six-role research tribunal with differentiated contracts;
- an official OpenAI provider using strict structured outputs and no tool access;
- explicit human approval and a locked experiment constitution;
- narrow, hash-bound C++ evidence execution and admission;
- SQLite persistence, tamper-evident audit history, export, verification, and reconstruction;
- a governed offline flagship demonstration with machine and human reports;
- a versioned 24-case comparative benchmark with single-agent and planner–reviewer baselines;
- adversarial regressions, independent audit records, hash-locked dependencies, and protected GitHub
  workflows.

### Current boundary

The submission demonstration uses a deterministic mock provider. It proves that the governed
provider boundary, numerical execution, evidence controls, persistence, verdict policy, export, and
replay work together. It does not prove live-model quality or profitability. The official OpenAI
integration exists, but funded live contract verification and live comparative transport remain
pending.

QuantForge is not a broker, strategy generator, trading system, market-data service, dashboard, or
investment adviser. Its current evidence is synthetic and is intended to validate the research
governance architecture.

## Inspiration

The project started from a simple frustration: backtests often become more convincing as their
research history becomes less visible. A final return can hide how many choices were tried, whether
the benchmark was fair, or whether contrary evidence survived the reporting process. I wanted to
build something closer to a research tribunal than another strategy-search tool—a system designed
to keep the protocol, evidence, objections, and verdict limit together.

## What it does

QuantForge turns a research claim into a stateful, replayable case. It asks specialized roles to
propose and review the experiment, requires a human approval before locking the constitution, runs a
trusted C++ numerical fixture, admits only identity-bound evidence, preserves adversarial findings,
and computes the verdict with deterministic code. It then exports both human-readable and
machine-readable reports that can be independently verified and reconstructed.

## How it was built

I began with a deterministic C++ event-driven backtester and frozen project-owned synthetic data.
The first QuantForge layer established the trust boundary: strict schemas, canonical hashing,
tamper-evident audit events, evidence graphs, and a pure verdict policy. I then added durable SQLite
storage and a narrow adapter to the protected C++ `v1.0.0` release.

The next stage introduced the six-role tribunal and the official structured OpenAI provider. Each
role has a separate request, schema, validation policy, and allowed state transition. The governed
offline demonstration connects those roles to real C++ execution using deterministic fixture
responses. Finally, I built a 24-case comparative benchmark and fair single-agent and
planner–reviewer baselines, then used adversarial remediation, independent audit reports,
hash-locked environments, and protected GitHub pull requests to harden the result.

## Challenges

The hardest challenge was preventing authority from leaking into model output. A schema alone is not
enough: a valid-looking response could still reference fabricated evidence, replay an old revision,
or imply a stronger verdict. I had to bind accepted outputs to the case, role, request, revision,
constitution, evidence inventory, and provider identity, then replay each transition to prove it did
not advance twice.

Another challenge was keeping deterministic and observational identity separate. Execution times
and raw observations can change without changing the governed meaning of a case. The export needed
to preserve both while providing a stable semantic identity. Packaging the flagship so it runs from
installed wheel and source distributions without weakening the protected C++ boundary also required
careful testing.

## Accomplishments

I am proud that the flagship result ends in INCONCLUSIVE even though 185.43% is the most visually
attractive number. The system reconstructs all 12 durable revisions, verifies six governed role
transactions, reports zero duplicate transitions, and preserves the decisive statistical and
robustness objections.

I also completed a closed 24-case comparative export across three architectures, release-integrity
records for both repositories, high-coverage malicious-input regressions, package smoke tests, and a
protected GitHub workflow. The project can explain exactly which parts are model-generated, which
numbers come from C++, and which decisions remain code-owned.

## What I learned

I learned that trustworthy model integration depends more on authority design than on prompt
wording. It is useful to ask a model for a critique, but the surrounding system still has to decide
what evidence exists, which revision is current, whether a transition is legal, and how strong the
verdict may be.

I also learned to treat reproducibility as a product behavior rather than a final documentation
task. Building export and replay early exposed ambiguous identities and hidden assumptions that
would have been difficult to repair later. Most importantly, an inconclusive result can be valuable
when it is the honest boundary of the evidence.

## What comes next

The immediate next step is a separately funded live OpenAI contract verification using the existing
strict provider and bounded runbook. After that, I want to run the comparative benchmark through an
approved live transport and invite external reproduction. Longer-term work includes independently
anchored audit evidence and broader empirical validation under reviewed data licenses. Broker
connectivity, live trading, and unsupported profitability claims are not on the current roadmap.

## Technologies used

- Python 3.12;
- modern C++ and CMake;
- OpenAI Python SDK with strict structured outputs;
- Pydantic;
- SQLite;
- Pytest, branch coverage, Ruff, and mypy;
- canonical JSON and SHA-256 evidence identities;
- CycloneDX SBOM and hash-locked dependencies;
- GitHub Actions, CodeQL, secret scanning, protected branches, and immutable QuantForge releases;
- Mermaid for the submission architecture diagram.

## Codex and GPT-5.6 contribution

I used Codex and GPT-5.6 as engineering collaborators under my direction. They helped me decompose
requirements, draft bounded implementations, construct adversarial tests, review trust boundaries,
trace evidence and release requirements, investigate failures, and edit technical documentation. I
set the architecture and scope, reviewed the code, decided which findings required remediation, and
controlled every release and merge decision.

The project was not generated by an autonomous agent, and ChatGPT is not presented as its author.
Codex and GPT-5.6 supported an iterative engineering process whose acceptance criteria, governance,
testing, and publication decisions remained student-directed.
