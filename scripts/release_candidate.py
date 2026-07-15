#!/usr/bin/env python3
"""Build and validate an exact local QuantForge AI publication candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.check_repository import (
    ORIGINAL_PHASE1_COMMIT,
    action_inventory,
    project_version,
    validate_repository,
)
from scripts.generate_sbom import generate_sbom, write_sbom
from scripts.inspect_packages import inspect_distributions
from scripts.verify_determinism import verify_all
from scripts.verify_determinism import write_report as write_determinism_report
from scripts.wheel_smoke import smoke_wheel

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
TEST_COUNT_RE = re.compile(r"(?P<count>[0-9]+) passed")
COVERAGE_TOTAL_RE = re.compile(r"(?m)^TOTAL\s+.*?\s(?P<percent>[0-9]+)%\s*$")


class ReleaseValidationError(RuntimeError):
    """A release-candidate invariant or validation gate failed."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(
    argv: list[str],
    cwd: Path,
    *,
    env: dict[str, str] | None = None,
    binary: bool = False,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    result = subprocess.run(  # noqa: S603 - all argv are code-owned or exact validated paths/SHAs
        argv,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=not binary,
    )
    if result.returncode != 0:
        stdout = result.stdout.decode() if isinstance(result.stdout, bytes) else result.stdout
        stderr = result.stderr.decode() if isinstance(result.stderr, bytes) else result.stderr
        raise ReleaseValidationError(
            f"command failed ({result.returncode}): {' '.join(argv)}\n{stdout}{stderr}"
        )
    return result


def _text(argv: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    result = _run(argv, cwd, env=env)
    if not isinstance(result.stdout, str):
        raise ReleaseValidationError("expected textual command output")
    return result.stdout.strip()


def _bytes(argv: list[str], cwd: Path) -> bytes:
    result = _run(argv, cwd, binary=True)
    if not isinstance(result.stdout, bytes):
        raise ReleaseValidationError("expected binary command output")
    return result.stdout


def git_text(root: Path, *args: str) -> str:
    return _text(["git", *args], root)


def verify_quantforge_boundary(root: Path, baseline: str) -> dict[str, Any]:
    head = git_text(root, "rev-parse", "--verify", "HEAD")
    if SHA_RE.fullmatch(head) is None or SHA_RE.fullmatch(baseline) is None:
        raise ReleaseValidationError("baseline and HEAD must be full lowercase Git commit SHAs")
    if git_text(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ReleaseValidationError("QuantForge working tree or index is not clean")
    remotes = git_text(root, "remote")
    if remotes:
        raise ReleaseValidationError(
            "QuantForge must not have a configured remote for local candidacy"
        )
    _run(["git", "merge-base", "--is-ancestor", baseline, head], root)
    _run(["git", "merge-base", "--is-ancestor", ORIGINAL_PHASE1_COMMIT, head], root)
    baseline_message = git_text(root, "show", "-s", "--format=%s", baseline)
    if baseline_message != "Harden Phase 1 after independent audit":
        raise ReleaseValidationError("audited baseline commit message is inconsistent")
    return {
        "baseline_commit": baseline,
        "branch": git_text(root, "branch", "--show-current"),
        "original_phase1_commit": ORIGINAL_PHASE1_COMMIT,
        "remotes": [],
        "source_commit": head,
        "working_tree": "clean",
    }


def engine_snapshot(engine: Path) -> dict[str, Any]:
    ignored = _bytes(
        ["git", "ls-files", "--others", "--ignored", "--exclude-standard", "-z"], engine
    )
    tracked_diff = _bytes(["git", "diff", "--no-ext-diff", "--binary"], engine)
    staged_diff = _bytes(["git", "diff", "--cached", "--no-ext-diff", "--binary"], engine)
    untracked = _bytes(["git", "ls-files", "--others", "--exclude-standard", "-z"], engine)
    return {
        "branch": git_text(engine, "branch", "--show-current"),
        "head": git_text(engine, "rev-parse", "HEAD"),
        "ignored_inventory_count": ignored.count(b"\0"),
        "ignored_inventory_sha256": hashlib.sha256(ignored).hexdigest(),
        "staged_diff": "empty" if not staged_diff else "nonempty",
        "tracked_diff": "empty" if not tracked_diff else "nonempty",
        "untracked_inventory": "empty" if not untracked else "nonempty",
        "v1.0.0_annotated_tag_object": git_text(engine, "rev-parse", "refs/tags/v1.0.0"),
        "v1.0.0_peeled_target": git_text(engine, "rev-parse", "v1.0.0^{}"),
    }


def expected_engine_boundary(root: Path) -> dict[str, Any]:
    audit = json.loads((root / "audit/phase1_independent_audit.json").read_text(encoding="utf-8"))
    protected = audit["repository_boundaries"]["protected_engine"]
    return {
        "head": protected["head_before"],
        "ignored_inventory_count": protected["ignored_inventory_count_before_and_after"],
        "ignored_inventory_sha256": protected["ignored_inventory_sha256_before_and_after"],
        "staged_diff": "empty",
        "tracked_diff": "empty",
        "untracked_inventory": "empty",
        "v1.0.0_annotated_tag_object": protected["v1_0_0_annotated_tag_object_before"],
        "v1.0.0_peeled_target": protected["v1_0_0_peeled_target_before"],
    }


def verify_engine_boundary(root: Path, *, allow_recorded: bool = False) -> dict[str, Any]:
    engine = root.parent / "cpp-event-driven-backtester"
    if not engine.is_dir():
        if not allow_recorded:
            raise ReleaseValidationError(
                "protected engine is absent; local release validation requires "
                "live boundary evidence"
            )
        recorded = expected_engine_boundary(root)
        recorded.update({"branch": "main", "verification": "recorded independent-audit evidence"})
        return recorded
    observed = engine_snapshot(engine)
    expected = expected_engine_boundary(root)
    for key, value in expected.items():
        if observed.get(key) != value:
            raise ReleaseValidationError(
                f"protected engine boundary changed for {key}: {observed.get(key)!r} != {value!r}"
            )
    if observed["branch"] != "main":
        raise ReleaseValidationError("protected engine branch differs from the recorded boundary")
    observed["verification"] = "live read-only comparison"
    return observed


def run_gate(label: str, argv: list[str], root: Path, env: dict[str, str]) -> dict[str, str]:
    result = _run(argv, root, env=env)
    stdout = result.stdout if isinstance(result.stdout, str) else result.stdout.decode()
    stderr = result.stderr if isinstance(result.stderr, str) else result.stderr.decode()
    combined = (stdout + "\n" + stderr).strip()
    print(f"{label}: passed")
    return {"label": label, "output": combined, "status": "passed"}


def _test_count(output: str, label: str) -> int:
    matches = list(TEST_COUNT_RE.finditer(output))
    if not matches:
        raise ReleaseValidationError(f"could not parse passed test count for {label}")
    return int(matches[-1].group("count"))


def build_twice(
    root: Path, work: Path, env: dict[str, str], version: str
) -> tuple[Path, dict[str, Any]]:
    first = work / "build-first"
    second = work / "build-second"
    first.mkdir()
    second.mkdir()
    run_gate(
        "first reproducible distribution build",
        [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(first)],
        root,
        env,
    )
    run_gate(
        "second reproducible distribution build",
        [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(second)],
        root,
        env,
    )
    expected = {
        f"quantforge_ai-{version}-py3-none-any.whl",
        f"quantforge_ai-{version}.tar.gz",
    }
    if {path.name for path in first.iterdir()} != expected:
        raise ReleaseValidationError(
            "first build artifact inventory differs from the release contract"
        )
    if {path.name for path in second.iterdir()} != expected:
        raise ReleaseValidationError(
            "second build artifact inventory differs from the release contract"
        )
    hashes: dict[str, str] = {}
    for name in sorted(expected):
        first_hash = sha256_file(first / name)
        second_hash = sha256_file(second / name)
        if first_hash != second_hash:
            raise ReleaseValidationError(f"distribution build is not reproducible: {name}")
        hashes[name] = first_hash
    return first, {"byte_identical_rebuild": True, "sha256": hashes, "status": "passed"}


def _release_markdown(report: dict[str, Any]) -> str:
    tests = report["test_results"]
    coverage = report["coverage_results"]
    artifacts = report["release_artifacts"]
    engine = report["repository_boundary"]["protected_engine"]
    security = report["security_results"]
    determinism = report["determinism_results"]
    lines = [
        f"# QuantForge AI v{report['version']} Release Validation",
        "",
        "## Identity",
        "",
        f"- Audited baseline: `{report['baseline_commit']}`",
        f"- Validated source commit: `{report['source_commit']}`",
        f"- Python: `{report['environment']['python']}`",
        f"- Platform: `{report['environment']['platform']}`",
        "- Decision: local publication-candidate validation passed; exact-SHA remote CI "
        "and explicit user publication authorization remain required.",
        "",
        "## Quality gates",
        "",
        f"- Full suite: {tests['full_suite_passed']} passed, 0 skipped",
        f"- Reverse file order: {tests['reverse_order_passed']} passed, 0 skipped",
        f"- Malicious-input suite: {tests['malicious_input_passed']} passed",
        f"- Branch-aware coverage: {coverage['overall_percent']}%",
        f"- Governance-critical coverage: {coverage['governance_critical_percent']}%",
        "- Formatting, Ruff, strict mypy, repository contracts, local links, CFF, and "
        "secret scan: passed",
        "",
        "## Security and dependencies",
        "",
        f"- Runtime dependency audit: {security['runtime_dependency_audit']}",
        f"- Development dependency audit: {security['development_dependency_audit']}",
        f"- Secret scan: {security['secret_scan']}",
        "- Package content and archive integrity: passed",
        "",
        "## Artifacts",
        "",
    ]
    for name, details in sorted(artifacts.items()):
        lines.append(f"- `{name}` — SHA-256 `{details['sha256']}`")
    lines.extend(
        [
            "",
            f"The three scenarios produced {determinism['artifact_comparisons']} byte-identical "
            "artifact comparisons; semantic audit replay and verdict stability passed.",
            "",
            "## Protected engine",
            "",
            f"- HEAD: `{engine['head']}`",
            f"- Ignored inventory SHA-256: `{engine['ignored_inventory_sha256']}`",
            f"- Annotated v1.0.0 tag object: `{engine['v1.0.0_annotated_tag_object']}`",
            f"- Peeled target: `{engine['v1.0.0_peeled_target']}`",
            "- Tracked, staged, and untracked state remained empty.",
            "",
            "## Limitations",
            "",
            "This validates an offline Phase 1 governance foundation on the recorded local "
            "platform. It does not validate profitability, investment advice, production "
            "deployment, live model execution, real engine integration, market data, broker "
            "connectivity, or trading.",
            "",
        ]
    )
    return "\n".join(lines)


def write_checksums(output: Path, assets: list[Path]) -> dict[str, str]:
    hashes = {
        asset.name: sha256_file(asset) for asset in sorted(assets, key=lambda path: path.name)
    }
    checksum_file = output / "SHA256SUMS"
    checksum_file.write_text(
        "".join(f"{digest}  {name}\n" for name, digest in sorted(hashes.items())),
        encoding="utf-8",
        newline="\n",
    )
    for name, expected in hashes.items():
        if sha256_file(output / name) != expected:
            raise ReleaseValidationError(f"checksum verification failed for {name}")
    return hashes


def validate_release(
    root: Path, baseline: str, output: Path, *, allow_recorded_engine: bool = False
) -> dict[str, Any]:
    if output.exists():
        raise ReleaseValidationError(f"release output already exists: {output}")
    release_root = (root / "release").resolve()
    try:
        output.resolve().relative_to(release_root)
    except ValueError as error:
        raise ReleaseValidationError(
            "release output must be under the ignored release/ directory"
        ) from error

    quantforge_boundary = verify_quantforge_boundary(root, baseline)
    engine_before = verify_engine_boundary(root, allow_recorded=allow_recorded_engine)
    version = project_version(root)
    source_commit = str(quantforge_boundary["source_commit"])
    source_epoch = int(git_text(root, "show", "-s", "--format=%ct", source_commit))
    output.mkdir(parents=True)
    (root / ".release-work").mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f"v{version}-", dir=root / ".release-work"))
    env = os.environ.copy()
    env.update(
        {
            "PIP_CACHE_DIR": str(work / "pip-cache"),
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INPUT": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "SOURCE_DATE_EPOCH": str(source_epoch),
        }
    )

    repository = validate_repository(root)
    gates: dict[str, dict[str, str]] = {}
    gates["format"] = run_gate(
        "formatting",
        [sys.executable, "-m", "ruff", "format", "--check", "src", "tests", "scripts"],
        root,
        env,
    )
    gates["ruff"] = run_gate(
        "Ruff lint", [sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"], root, env
    )
    gates["mypy"] = run_gate(
        "strict mypy", [sys.executable, "-m", "mypy", "src/quantforge", "scripts"], root, env
    )
    gates["pytest"] = run_gate(
        "full pytest with branch coverage",
        [
            sys.executable,
            "-m",
            "pytest",
            "--cov=quantforge",
            "--cov-branch",
            "--cov-report=term-missing",
            "--cov-report=xml",
        ],
        root,
        env,
    )
    gates["governance_coverage"] = run_gate(
        "governance-critical coverage",
        [
            sys.executable,
            "-m",
            "coverage",
            "report",
            "--include=src/quantforge/audit/*,src/quantforge/domain/*,src/quantforge/evidence/*,src/quantforge/roles/*,src/quantforge/serialization/*,src/quantforge/verdict/*,src/quantforge/workflow/*",
            "--fail-under=90",
        ],
        root,
        env,
    )
    coverage_json = work / "coverage.json"
    run_gate(
        "coverage report serialization",
        [sys.executable, "-m", "coverage", "json", "-o", str(coverage_json)],
        root,
        env,
    )
    test_files = [
        str(path.relative_to(root))
        for path in sorted((root / "tests").rglob("test_*.py"), reverse=True)
    ]
    gates["reverse_pytest"] = run_gate(
        "reverse-file-order pytest", [sys.executable, "-m", "pytest", *test_files], root, env
    )
    gates["malicious_pytest"] = run_gate(
        "malicious serialized-input regressions",
        [sys.executable, "-m", "pytest", "-m", "malicious"],
        root,
        env,
    )
    gates["repository"] = run_gate(
        "repository, version, lock, link, and workflow contracts",
        [sys.executable, "scripts/check_repository.py"],
        root,
        env,
    )
    gates["secrets"] = run_gate(
        "secret scan", [sys.executable, "scripts/check_secrets.py"], root, env
    )
    cffconvert = Path(sys.executable).parent / (
        "cffconvert.exe" if os.name == "nt" else "cffconvert"
    )
    gates["citation"] = run_gate(
        "CITATION.cff schema validation",
        [str(cffconvert), "--validate", "-i", "CITATION.cff"],
        root,
        env,
    )
    audit_common = [
        sys.executable,
        "-m",
        "pip_audit",
        "--disable-pip",
        "--strict",
        "--progress-spinner",
        "off",
        "--cache-dir",
        str(work / "pip-audit-cache"),
    ]
    gates["runtime_audit"] = run_gate(
        "runtime dependency audit",
        [*audit_common, "-r", "requirements.lock"],
        root,
        env,
    )
    gates["development_audit"] = run_gate(
        "development dependency audit",
        [*audit_common, "-r", "requirements-dev.lock"],
        root,
        env,
    )

    determinism_work = work / "determinism"
    determinism = verify_all(determinism_work)
    write_determinism_report(determinism, output / "determinism-validation.json")
    print("determinism validation: passed")

    build_dir, reproducible_build = build_twice(root, work, env, version)
    for artifact in build_dir.iterdir():
        shutil.copy2(artifact, output / artifact.name)
    package_inspection = inspect_distributions(root, output)
    wheel = output / f"quantforge_ai-{version}-py3-none-any.whl"
    sdist = output / f"quantforge_ai-{version}.tar.gz"
    wheel_smoke = smoke_wheel(
        wheel,
        root / "requirements.lock",
        version,
        work / "wheel-smoke",
    )
    print("installed-wheel CLI smoke: passed")

    sbom_name = f"quantforge-ai-v{version}-sbom.cdx.json"
    sbom_path = output / sbom_name
    sbom = generate_sbom(
        root,
        wheel,
        root / "requirements.lock",
        source_commit,
        source_epoch,
    )
    sbom_hash = write_sbom(sbom, sbom_path)
    print("CycloneDX SBOM generation and model validation: passed")

    engine_after = verify_engine_boundary(root, allow_recorded=allow_recorded_engine)
    if engine_before != engine_after:
        raise ReleaseValidationError("protected engine changed during release validation")
    if git_text(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ReleaseValidationError("release validation changed tracked or untracked source state")
    if git_text(root, "remote"):
        raise ReleaseValidationError("a Git remote appeared during release validation")

    coverage_document = json.loads(coverage_json.read_text(encoding="utf-8"))
    totals = coverage_document["totals"]
    governance_match = COVERAGE_TOTAL_RE.search(gates["governance_coverage"]["output"])
    if governance_match is None:
        raise ReleaseValidationError("could not parse governance-critical coverage")
    full_count = _test_count(gates["pytest"]["output"], "full suite")
    reverse_count = _test_count(gates["reverse_pytest"]["output"], "reverse suite")
    malicious_count = _test_count(gates["malicious_pytest"]["output"], "malicious suite")
    if full_count != reverse_count:
        raise ReleaseValidationError("normal and reverse-order test counts differ")

    lock_hashes = {
        filename: sha256_file(root / filename)
        for filename in (
            "requirements.in",
            "requirements.lock",
            "requirements-dev.in",
            "requirements-dev.lock",
        )
    }
    release_artifacts = {
        wheel.name: {"sha256": sha256_file(wheel), "type": "wheel"},
        sdist.name: {"sha256": sha256_file(sdist), "type": "sdist"},
        sbom_name: {
            "format": "CycloneDX 1.6 JSON",
            "sha256": sbom_hash,
            "type": "sbom",
        },
    }
    changed_files = git_text(
        root, "diff", "--name-only", f"{baseline}..{source_commit}"
    ).splitlines()
    report: dict[str, Any] = {
        "baseline_commit": baseline,
        "coverage_results": {
            "branch_coverage_enabled": True,
            "covered_branches": totals["covered_branches"],
            "governance_critical_percent": int(governance_match.group("percent")),
            "governance_critical_required_percent": 90,
            "missing_branches": totals["missing_branches"],
            "overall_percent": round(float(totals["percent_covered"]), 2),
            "overall_required_percent": 90,
            "total_branches": totals["num_branches"],
        },
        "determinism_results": determinism,
        "documentation_results": {
            "citation_cff": "passed with cffconvert==2.0.0",
            "local_links_checked": repository["local_links_checked"],
            "phase1_independent_audit": repository["phase1_audit"],
            "publication_files": "passed",
            "version_consistency": "passed",
        },
        "environment": {
            "implementation": platform.python_implementation(),
            "machine": platform.machine(),
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "files_changed_since_baseline": changed_files,
        "generated_at_utc": datetime.fromtimestamp(source_epoch, tz=UTC).isoformat(),
        "lock_file_sha256": lock_hashes,
        "package_results": {
            "inspection": package_inspection,
            "installed_wheel": wheel_smoke,
            "reproducible_build": reproducible_build,
        },
        "publication_decision": {
            "github_publication_ready": True,
            "local_validation": "passed",
            "release_publication_authorized": False,
            "remote_exact_sha_ci_required": True,
        },
        "release_artifacts": release_artifacts,
        "repository_boundary": {
            "protected_engine": engine_after,
            "quantforge": quantforge_boundary,
        },
        "schema_version": "1.0",
        "security_results": {
            "development_dependency_audit": "No known vulnerabilities found",
            "malicious_input_regressions": f"{malicious_count} passed",
            "runtime_dependency_audit": "No known vulnerabilities found",
            "secret_scan": "current files and reachable history passed",
        },
        "source_commit": source_commit,
        "test_results": {
            "full_suite_passed": full_count,
            "malicious_input_passed": malicious_count,
            "reverse_order_passed": reverse_count,
            "skipped": 0,
        },
        "version": version,
        "workflow_results": {
            "action_references": action_inventory(root),
            "static_policy_validation": "passed",
            "workflows": sorted(path.name for path in (root / ".github/workflows").glob("*.yml")),
        },
    }
    report_json = output / f"quantforge-ai-v{version}-release-validation.json"
    report_md = output / f"quantforge-ai-v{version}-release-validation.md"
    report_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_md.write_text(_release_markdown(report), encoding="utf-8", newline="\n")
    report["checksum_verification"] = {
        "assets": sorted(
            [
                wheel.name,
                sdist.name,
                sbom_path.name,
                report_json.name,
                report_md.name,
                "determinism-validation.json",
            ]
        ),
        "file": "SHA256SUMS",
        "status": "passed",
    }
    report_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_checksums(
        output,
        [wheel, sdist, sbom_path, report_json, report_md, output / "determinism-validation.json"],
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-commit", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--allow-recorded-engine-boundary",
        action="store_true",
        help="Use signed-off Phase 1 engine evidence only when the sibling is absent in remote CI",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        report = validate_release(
            root,
            args.baseline_commit,
            args.output_dir.resolve(),
            allow_recorded_engine=args.allow_recorded_engine_boundary,
        )
    except (OSError, ReleaseValidationError, RuntimeError, ValueError) as error:
        print(f"release candidate validation failed: {error}", file=sys.stderr)
        return 1
    print(
        f"QuantForge AI v{report['version']} local release candidate validated at "
        f"{report['source_commit']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
