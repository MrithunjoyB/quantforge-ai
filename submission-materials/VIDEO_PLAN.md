# QuantForge demo video plan

Target length: **3 minutes 40 seconds**. Record at 1920×1080, 30 fps, with a terminal font large
enough to read at 720p. The demonstration is the deterministic mock-provider path; do not imply that
the role text came from a live OpenAI call.

## Recording preparation

Generate the two artifact sets before recording so no dependency download, compilation, or loading
screen appears in the final cut:

```bash
./scripts/run_judge_demo.sh ../cpp-event-driven-backtester /private/tmp/quantforge-video-demo
.venv/bin/quantforge evaluation compare --subset full \
  --output-dir /private/tmp/quantforge-video-evaluation
.venv/bin/quantforge evaluation verify-export /private/tmp/quantforge-video-evaluation
.venv/bin/quantforge evaluation replay /private/tmp/quantforge-video-evaluation
```

Open these views in advance:

1. the first screen of `README.md`;
2. `submission-materials/ARCHITECTURE.md` rendered on GitHub;
3. a terminal containing the concise demo summary;
4. `/private/tmp/quantforge-video-demo/tribunal-report.md`;
5. `/private/tmp/quantforge-video-demo/evidence-manifest.json` in a readable JSON viewer;
6. `/private/tmp/quantforge-video-evaluation/evaluation-report.md`;
7. the README section “How Codex and GPT-5.6 were used.”

## Exact timeline and voiceover

### 0:00–0:20 — The problem

**Screen:** README title, subtitle, tagline, and first paragraph.

**Callout:** “A persuasive backtest can still be wrong.”

**Voiceover:**

> This is QuantForge, a research tribunal for quantitative claims. I built it because a backtest can
> be numerically correct and still support an unreliable story. Hidden selection, weak benchmarks,
> unrealistic costs, or missing evidence can make a result look much stronger than it is.

### 0:20–0:48 — The governed path

**Screen:** Rendered architecture diagram. Pan once from claim to export; do not scroll source code.

**Callouts:** “Model proposes and reviews” and “Code owns evidence and verdict.”

**Voiceover:**

> A claim becomes a governed experiment. Model roles propose the protocol and review methodology,
> statistics, adversarial risks, and reproducibility. A human approval locks the constitution before
> execution. The C++ engine owns the numbers, and deterministic QuantForge code owns evidence
> admission, workflow state, and the verdict. The Chair can explain the result, but cannot change it.

### 0:48–1:05 — One-command demonstration

**Screen:** Show the command, then cut directly to the completed concise summary.

```bash
./scripts/run_judge_demo.sh ../cpp-event-driven-backtester /private/tmp/quantforge-video-demo
```

**Callout:** “OFFLINE GOVERNED DEMONSTRATION — MOCK PROVIDER.”

**Voiceover:**

> This submission demo uses the deterministic mock provider. The wrapper checks the environment,
> builds the protected C++ release outside the repositories, runs the case, writes the reports, and
> verifies the export. It makes no live OpenAI call.

### 1:05–1:42 — The attractive result and contrary evidence

**Screen:** Human report evidence table. Highlight one row at a time.

**Callouts, in order:**

1. “185.43% total return”;
2. “−42.47% maximum drawdown”;
3. “Corrected p-value: 0.308691”;
4. “Bootstrap loss probability: 25.2%.”

**Voiceover:**

> The headline is deliberately attractive: a 185.43 percent total return and 100.97 percent excess
> return after declared costs. But the same admitted evidence reports a minus 42.47 percent drawdown,
> a corrected p-value around 0.309 against a 0.05 criterion, and a 25.2 percent bootstrap probability
> of loss against a 10 percent limit. The return interval also crosses zero.

### 1:42–2:10 — Code-owned verdict

**Screen:** Terminal summary and verdict section of the report.

**Callout:** “INCONCLUSIVE — computed before the Chair runs.”

**Voiceover:**

> Reproducibility passes, but statistical reliability and robustness do not. QuantForge therefore
> computes INCONCLUSIVE before the Chair receives the case. That is the point of the project: the
> attractive return survives as evidence, but it cannot become a stronger claim than the complete
> case supports.

### 2:10–2:40 — Evidence identity and reconstruction

**Screen:** `evidence-manifest.json`, then the verification JSON from the terminal.

**Callouts:** “12 durable revisions,” “6 role transactions,” “0 duplicate transitions,” and the
shortened demonstration SHA-256.

**Voiceover:**

> Every important fact is tied to an artifact location and SHA-256 identity. The export contains the
> case, evidence ledger, claim graph, audit events, and manifest. Independent verification rejects
> missing or substituted files, reconstructs all 12 revisions, checks six role transactions, and
> confirms that replay created zero duplicate transitions.

### 2:40–3:12 — Comparative benchmark

**Screen:** `evaluation-report.md`, showing the architecture definitions and primary metric table.

**Callout:** “24 cases × 3 architectures = 72 verified results.”

**Voiceover:**

> I also built a 24-case benchmark covering research defects, evidence attacks, authority violations,
> reproducibility failures, and a sound control. It compares a single agent, a planner–reviewer, and
> the real six-role tribunal under the same deterministic fixture and budgets. These 72 results
> validate routing, scoring, persistence, and authority enforcement—not live model intelligence or
> global superiority.

### 3:12–3:40 — Codex, GPT-5.6, and current status

**Screen:** README contribution section, then return to the project title.

**Callout:** “Student-directed architecture, review, testing, and release decisions.”

**Voiceover:**

> I used Codex and GPT-5.6 as engineering collaborators for decomposition, implementation drafts,
> adversarial testing, failure investigation, and technical editing. I directed the architecture,
> scope, review, and release decisions. The official structured OpenAI provider exists, but funded
> live verification is still pending. Today’s claim is narrower and verifiable: QuantForge can keep
> a persuasive backtest from outrunning its evidence.

## Backup shortened version (about 2 minutes)

- **0:00–0:15:** State the problem over the README opening.
- **0:15–0:35:** Show the architecture and explain the model/code/C++ boundaries.
- **0:35–1:10:** Show 185.43%, −42.47%, p≈0.309, and 25.2% in the report.
- **1:10–1:30:** Show INCONCLUSIVE and the verified reconstruction output.
- **1:30–1:47:** Show the 24-case, three-architecture benchmark report.
- **1:47–2:00:** State the Codex/GPT-5.6 contribution and pending live verification.

Short closing line:

> QuantForge does not ask whether a backtest is exciting. It asks how much trust its evidence can
> actually carry.

## Recording checklist

- [ ] Use a clean browser profile with no private tabs, bookmarks, notifications, or account menus.
- [ ] Use a terminal prompt that contains no username, home directory, token, or private path.
- [ ] Prebuild the artifacts; remove compilation and loading time in the edit.
- [ ] Keep the mock-provider label visible when the demo result first appears.
- [ ] Confirm all four required numbers are sharp and readable at 720p.
- [ ] Show the full word `INCONCLUSIVE`, not only a coloured badge.
- [ ] Show evidence identity and the successful reconstruction result.
- [ ] Show the 24-case comparative report and its offline interpretation boundary.
- [ ] State that the official OpenAI integration exists and funded live verification is pending.
- [ ] State the student-directed Codex and GPT-5.6 contribution accurately.
- [ ] Do not show dependency installation, compilation, loading screens, raw source scrolling, or
  credentials.
- [ ] Listen once with the screen hidden to check that the narration stands on its own.
- [ ] Watch the final upload at 720p and 1080p in an incognito window.

## YouTube metadata

**Title:**

QuantForge — A Research Tribunal for Quantitative Claims | OpenAI Build Week

**Description:**

> QuantForge tests whether a quantitative claim deserves trust. This demo follows an attractive
> 185.43% synthetic backtest through methodology, statistical, adversarial, and reproducibility
> review. The same evidence reveals a −42.47% drawdown, a corrected p-value near 0.309, and a 25.2%
> bootstrap loss probability, so deterministic code limits the verdict to INCONCLUSIVE.
>
> The demonstration uses QuantForge’s offline deterministic mock provider and the protected C++
> `v1.0.0` numerical engine. The official structured OpenAI provider exists, but funded live
> verification remains pending. No investment advice, live trading, or profitability claim is made.
>
> Repository: [insert public repository URL]
> Devpost: [insert final Devpost URL]

**Thumbnail text:**

**185.43% RETURN. VERDICT: INCONCLUSIVE.**

Use a smaller subtitle: **Can the evidence be trusted?**
