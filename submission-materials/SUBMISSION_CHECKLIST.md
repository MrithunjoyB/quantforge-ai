# OpenAI Build Week submission checklist

This checklist separates repository evidence from actions that must be performed manually by the
student. Do not mark a manual item complete based only on a local test.

## Repository and build

- [ ] Confirm protected `main` is clean and record the final 40-character SHA.
- [ ] Confirm the final SHA descends from baseline
  `09318da86cace5b54fedaea3a8a39a106c764965`.
- [ ] Confirm the protected C++ repository is clean and unchanged.
- [ ] Run `scripts/quality.sh` on the final submission commit.
- [ ] Run both dependency audits from the reviewed lockfiles.
- [ ] Build and inspect the wheel and source distribution.
- [ ] Test the README setup from a new environment outside the source tree.
- [ ] Test the judge wrapper with `.venv/bin/quantforge`.
- [ ] Test the judge wrapper with an installed `quantforge` command via `QUANTFORGE_CLI`.
- [ ] Confirm the wrapper leaves both source trees unchanged.

## Demo and evidence

- [ ] Generate a fresh flagship artifact set outside both repositories.
- [ ] Confirm the label reads `OFFLINE GOVERNED DEMONSTRATION — MOCK PROVIDER`.
- [ ] Confirm the headline return is 185.43%.
- [ ] Confirm maximum drawdown is −42.47%.
- [ ] Confirm the corrected p-value is approximately 0.309.
- [ ] Confirm bootstrap loss probability is 25.2%.
- [ ] Confirm the code-owned verdict is `INCONCLUSIVE`.
- [ ] Run independent demo verification and record the semantic SHA-256.
- [ ] Confirm durable reconstruction passes with 12 revisions and zero duplicate transitions.
- [ ] Generate, verify, replay, and report the 24-case comparative evaluation.
- [ ] Confirm the comparative material is labeled as deterministic mock-provider evaluation.

## README and submission materials

- [ ] Test every README command exactly as shown.
- [ ] Check every local README link.
- [ ] Render the Mermaid diagram on GitHub and check it at desktop and mobile widths.
- [ ] Read the Devpost drafts aloud and make any final student-voice edits.
- [ ] Confirm no statement presents synthetic evidence as live profitability.
- [ ] Confirm no statement presents mock role output as live OpenAI output.
- [ ] Confirm C++ `v1.0.0` is described as tag-protected and asset-hash verified, while its GitHub
  native immutable flag remains false.
- [ ] Confirm QuantForge `v0.1.0` is described as GitHub-native immutable.
- [ ] Scan the final diff for secrets, private paths, stale SHAs, unsupported claims, and broken links.

## Protected GitHub workflow

- [ ] Push only `codex/hackathon-submission-package`.
- [ ] Open a ready-for-review pull request into `main`.
- [ ] Confirm the PR contains only submission-related documentation, wrapper, tests, and narrow
  usability changes.
- [ ] Wait for every mandatory check on the exact PR head SHA.
- [ ] Resolve all review conversations.
- [ ] Merge normally using an allowed linear-history method; do not bypass protection.
- [ ] Update local `main` from the protected remote.
- [ ] Rerun the judge demo and verification after merge.
- [ ] Perform a final read-only submission audit and record the merged SHA below.

Final submission SHA: `________________________________________`

Pull request URL: `____________________________________________________________`

Merge method: `_______________________________________________________________`

## Video and YouTube — manual

- [ ] Record the 3–4 minute video using `VIDEO_PLAN.md`.
- [ ] Produce and retain the shortened backup cut.
- [ ] Check narration, labels, exact figures, and mock/live disclosure.
- [ ] Upload the final video to YouTube.
- [ ] Add the final title, description, repository URL, and Devpost URL.
- [ ] Confirm the video is public or unlisted as required by the rules.
- [ ] Watch the full upload in an incognito window with captions enabled.
- [ ] Test the YouTube URL from a logged-out device or browser.

## Devpost — manual

- [ ] Create the Devpost project.
- [ ] Populate every field from `DEVPOST.md`, editing as needed in the student's own voice.
- [ ] Add the public repository and final YouTube links.
- [ ] Add screenshots that visibly retain the mock-provider boundary.
- [ ] Confirm repository visibility or grant the required reviewer access.
- [ ] Retrieve and save the required Codex `/feedback` session ID.
- [ ] Accept all team invitations.
- [ ] Check team names, project ownership, and eligibility information.
- [ ] Preview the complete entry on desktop and mobile.
- [ ] Test every final link in an incognito window.
- [ ] Mark the final submission **Submitted**, not **Draft**.
- [ ] Capture a timestamped confirmation screenshot or receipt.

## Final sign-off

- [ ] No credentials, private paths, unpublished evidence, or personal data are visible.
- [ ] No live-provider, profitability, superiority, release-immutability, or feature claim exceeds the
  committed evidence.
- [ ] Remaining limitations and pending funded live OpenAI verification are easy to find.
- [ ] Final SHA, PR, YouTube, Devpost, and feedback-session references are stored safely.
