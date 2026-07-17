# Release Policy

QuantForge AI releases are transactional, exact-commit operations. A passing branch build is not a
release authorization, a tag is not created speculatively, and no ordinary push publishes a package
or GitHub release.

## Roles and evidence

The maintainer proposes a candidate and performs local validation. Remote CI independently evaluates
the same full commit SHA. A human release approver confirms the evidence and explicitly authorizes
tagging and publication. For `v0.1.0`, the audited baseline is recorded in the publication-candidate
audit reports; the protected C++ engine remains external and immutable.

Required evidence consists of the machine and human release-validation reports, complete gate logs,
wheel and sdist inventories, installed-wheel smoke results, deterministic scenario hashes, runtime
and development audit results, a CycloneDX SBOM, SHA-256 checksums, workflow/action-pin inventory,
and repository-boundary proof.

## Protected-engine repository boundary

The external C++ engine boundary is source-oriented. A live comparison requires the recorded
`main` branch, exact HEAD, exact tracked-tree object, empty tracked and staged diffs, no untracked
non-ignored paths, and the exact annotated `v1.0.0` tag object and peeled target. Those invariants
are blockers when they drift.

Ignored local state is classified and reported, not frozen as an immutable filesystem snapshot.
The bounded allowlist is derived from the engine's build, test, data, and output contracts:

- CMake and CTest output under `build/` or a named `build-*` root;
- generated `results/`, `test_results/`, `reproduced/`, distribution, and Matplotlib output;
- Python bytecode under `__pycache__/` and conventional local virtual environments;
- the documented local-data boundary and named compiler/test artifacts.

Every ignored entry must still be a regular in-repository file in one of those classes. Symlinks,
traversal, VCS or workflow-control paths, sensitive names, strong credential indicators, hidden
source outside CMake compiler-identification output or an installed virtual environment, and every
unknown ignored path remain blockers. Moving a sensitive or source file under an allowlisted parent
does not make it permissible. The NUL-delimited ignored path count and SHA-256 remain useful
diagnostic evidence and must be stable during one validation transaction, but ordinary generated
drift between separate local runs is not a released-source defect.

## Transactional procedure

1. **Clean source:** start from a clean working tree and index, no untracked publication input, no
   configured unexpected remote, and the exact reviewed release metadata.
2. **Exact audited lineage:** verify the intended candidate is a descendant of the independently
   audited Phase 1 baseline and record both 40-character commits.
3. **Complete local validation:** create a fresh Python environment from `requirements-dev.lock` with
   `--require-hashes`; run formatting, Ruff, strict mypy, full and reverse-order pytest, branch and
   governance-critical coverage, malicious-input regressions, secret and dependency scans,
   documentation/CFF/workflow checks, determinism, packaging, SBOM, checksum, and installed-wheel
   validation.
4. **Exact-SHA remote CI:** publish the source only after user authorization, then require CI,
   Security, CodeQL, Reproducibility, and manually dispatched Release Candidate workflows to pass on
   the same full SHA. A branch name or pull-request merge ref is insufficient evidence.
5. **Human approval and annotated tag:** compare local and remote evidence. After explicit approval,
   create one annotated `v0.1.0` tag at the approved SHA; use a cryptographically signed annotated tag
   when signing is configured. Never move or recreate the tag.
6. **Build from the approved tag:** check out the tag in a fresh environment and regenerate wheel,
   sdist, CycloneDX SBOM, release reports, and `SHA256SUMS`. The tag target must equal the approved
   candidate SHA and rebuilt artifact hashes must match approved reproducibility expectations.
7. **Publish assets together:** create a draft GitHub release for the immutable tag, attach the wheel,
   sdist, SBOM, checksums, and both validation reports, verify the displayed inventory, then publish
   once. Ordinary branch workflows have no publication permission.
8. **Record checksums and SBOM:** ensure every public release asset except `SHA256SUMS` itself is
   represented in the checksum file and that the SBOM root component, version, dependency graph, and
   wheel hash match the release.
9. **Independent post-release verification:** from a separate clean location, download the public
   assets, verify `SHA256SUMS`, validate the SBOM, install the wheel without the source tree, run
   `quantforge --version`, execute and validate the offline demo, and confirm the public tag target.
10. **Immutability:** enable tag protection/rulesets and immutable-release controls where available.
    Never replace a tag or asset. A defect requires a new version, new tag, changelog entry, and fresh
    evidence.

If any step fails, stop the transaction, preserve non-sensitive diagnostic evidence, reproduce and
repair the root cause on an untagged branch, add a regression test, and restart from step 1. Never
weaken a gate or edit an already published asset.

## Version and artifact contract

`src/quantforge/_version.py` is the authoritative software version. Hatch reads it for distribution
metadata; runtime imports it; the CLI reports it; repository checks reconcile it with the changelog,
`CITATION.cff`, release notes, SBOM, and validation reports.

For version `0.1.0`, the expected local output is:

- `quantforge_ai-0.1.0-py3-none-any.whl`
- `quantforge_ai-0.1.0.tar.gz`
- `quantforge-ai-v0.1.0-sbom.cdx.json`
- `SHA256SUMS`
- `quantforge-ai-v0.1.0-release-validation.json`
- `quantforge-ai-v0.1.0-release-validation.md`

CycloneDX 1.6 JSON is used because it is an open, machine-readable SBOM standard and the serializer
is supplied by the exact hash-locked `cyclonedx-python-lib` dependency of pinned `pip-audit`. The SBOM
generator records its own tool version, the root wheel digest, the runtime dependency graph, allowed
distribution hashes from `requirements.lock`, and deterministic source identity.

## CI and platform boundary

Local publication-candidate evidence is valid only for the recorded interpreter and operating
system. GitHub workflows target Python 3.12, 3.13, and 3.14 on pinned Ubuntu, plus Python 3.12 on
pinned macOS and Windows runner images. A platform is not claimed to pass until its remote job passes
for the exact candidate SHA. Release publication requires those remote results; this local task does
not establish them. Because the protected engine is deliberately not copied into the future GitHub
repository, remote release-candidate CI revalidates the committed independent-audit boundary record;
the local candidate must additionally pass a live read-only comparison against the sibling engine.
The genuine production C++ adapter contract is Linux/macOS only. Windows CI establishes package,
historical-fixture, and offline mock compatibility, not production adapter execution.
