#!/usr/bin/env python3
"""Validate publication metadata, documentation, locks, and workflow policy."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

VERSION_RE = re.compile(r'^__version__ = "(?P<version>[0-9]+\.[0-9]+\.[0-9]+)"$', re.MULTILINE)
ACTION_RE = re.compile(
    r"^\s*-?\s*uses:\s*(?P<action>[^@\s]+)@(?P<sha>[0-9a-f]{40})\s+#\s+(?P<version>v\S+)\s*$"
)
LINK_RE = re.compile(r"!?\[[^\]]*\]\((?P<target>[^)]+)\)")
REQUIREMENT_RE = re.compile(r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\s\\]+)")
LOWER_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
ORIGINAL_PHASE1_COMMIT = "2e9da09f4470a1c50e756a06ab935d90f1beaa7a"
PHASE1_VERDICT = "QUANTFORGE AI PHASE 1 INDEPENDENT AUDIT PASSED — READY FOR PHASE 2"

REQUIRED_PUBLICATION_FILES = {
    "README.md",
    "LICENSE",
    "NOTICE",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "CITATION.cff",
    "CODE_OF_CONDUCT.md",
    "SUPPORT.md",
    "docs/RELEASE_POLICY.md",
    "docs/RELEASE_NOTES_v0.1.0.md",
    "audit/phase1_independent_audit.json",
    "audit/phase1_independent_audit.md",
}
REQUIRED_WORKFLOWS = {
    "ci.yml",
    "security.yml",
    "codeql.yml",
    "reproducibility.yml",
    "release-candidate.yml",
}


class RepositoryCheckError(RuntimeError):
    """A publication repository invariant failed."""


def project_version(root: Path) -> str:
    """Read the one authoritative package version without importing the package."""
    version_file = root / "src/quantforge/_version.py"
    match = VERSION_RE.search(version_file.read_text(encoding="utf-8"))
    if match is None:
        raise RepositoryCheckError(
            "authoritative _version.py is missing a strict version assignment"
        )
    return match.group("version")


def _toml(root: Path) -> dict[str, Any]:
    return tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))


def check_required_files(root: Path) -> None:
    missing = sorted(path for path in REQUIRED_PUBLICATION_FILES if not (root / path).is_file())
    if missing:
        raise RepositoryCheckError(f"missing publication files: {missing}")


def check_version_contract(root: Path) -> str:
    version = project_version(root)
    configuration = _toml(root)
    project = configuration["project"]
    hatch = configuration["tool"]["hatch"]
    if project.get("dynamic") != ["version"] or "version" in project:
        raise RepositoryCheckError("pyproject must obtain its version dynamically from one source")
    if hatch.get("version", {}).get("path") != "src/quantforge/_version.py":
        raise RepositoryCheckError("Hatch version path does not reference the authoritative source")
    if project.get("dependencies") != ["pydantic==2.12.5"]:
        raise RepositoryCheckError("direct runtime dependencies must remain exactly pinned")
    if project.get("license") != "Apache-2.0":
        raise RepositoryCheckError(
            "package license metadata must use the Apache-2.0 SPDX expression"
        )
    if project.get("license-files") != ["LICENSE", "NOTICE"]:
        raise RepositoryCheckError("package license material must include LICENSE and NOTICE")

    init_text = (root / "src/quantforge/__init__.py").read_text(encoding="utf-8")
    if "from quantforge._version import __version__" not in init_text:
        raise RepositoryCheckError("runtime version does not import the authoritative source")

    expected_fragments = {
        "CHANGELOG.md": f"## [{version}]",
        "CITATION.cff": f"version: {version}",
        "docs/RELEASE_NOTES_v0.1.0.md": f"Version `{version}`",
        "README.md": f"Version `{version}`",
    }
    for relative, fragment in expected_fragments.items():
        if fragment not in (root / relative).read_text(encoding="utf-8"):
            raise RepositoryCheckError(f"{relative} does not identify version {version}")
    return version


def check_phase1_audit_readiness(root: Path) -> dict[str, Any]:
    """Validate the machine and human independent-audit decision and repaired findings."""
    json_path = root / "audit/phase1_independent_audit.json"
    markdown_path = root / "audit/phase1_independent_audit.md"
    try:
        document = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise RepositoryCheckError("Phase 1 machine-readable audit report is invalid") from error
    decision = document.get("decision")
    if not isinstance(decision, dict):
        raise RepositoryCheckError("Phase 1 audit decision is missing")
    if (
        document.get("audited_commit") != ORIGINAL_PHASE1_COMMIT
        or decision.get("status") != "passed"
        or decision.get("phase2_may_begin") is not True
        or decision.get("verdict") != PHASE1_VERDICT
    ):
        raise RepositoryCheckError("Phase 1 audit does not record the required passed decision")

    findings = document.get("findings")
    if not isinstance(findings, list):
        raise RepositoryCheckError("Phase 1 audit finding inventory is missing")
    repaired: list[str] = []
    for finding in findings:
        if not isinstance(finding, dict):
            raise RepositoryCheckError("Phase 1 audit contains an invalid finding")
        if finding.get("severity") not in {"Critical", "High", "Medium"}:
            continue
        identifier = finding.get("id")
        tests = finding.get("regression_tests")
        if (
            not isinstance(identifier, str)
            or finding.get("status") != "repaired"
            or not isinstance(tests, list)
            or not tests
            or not all(isinstance(test, str) and test for test in tests)
        ):
            raise RepositoryCheckError(
                f"Phase 1 Critical/High/Medium finding is not repair-complete: {identifier!r}"
            )
        repaired.append(identifier)
    if not repaired:
        raise RepositoryCheckError("Phase 1 audit records no repaired High or Medium findings")

    human_report = markdown_path.read_text(encoding="utf-8")
    if PHASE1_VERDICT not in human_report or "Phase 2 may begin" not in human_report:
        raise RepositoryCheckError("Phase 1 human audit report does not match the passed decision")
    return {
        "audited_commit": ORIGINAL_PHASE1_COMMIT,
        "repaired_critical_high_medium": repaired,
        "status": "passed",
        "verdict": PHASE1_VERDICT,
    }


def check_local_links(root: Path) -> int:
    checked = 0
    for document in sorted(root.rglob("*.md")):
        if any(part in {".git", ".venv", "build", "dist", "release"} for part in document.parts):
            continue
        text = document.read_text(encoding="utf-8")
        for match in LINK_RE.finditer(text):
            raw = match.group("target").strip()
            if raw.startswith("<") and ">" in raw:
                raw = raw[1 : raw.index(">")]
            else:
                raw = raw.split(maxsplit=1)[0]
            parsed = urlsplit(raw)
            if parsed.scheme or raw.startswith("#"):
                continue
            target_text = unquote(parsed.path)
            if not target_text:
                continue
            target = Path(target_text)
            if target.is_absolute():
                raise RepositoryCheckError(
                    f"absolute local link in {document.relative_to(root)}: {raw}"
                )
            resolved = (document.parent / target).resolve()
            try:
                resolved.relative_to(root.resolve())
            except ValueError as error:
                raise RepositoryCheckError(
                    f"link escapes repository in {document.relative_to(root)}: {raw}"
                ) from error
            if not resolved.exists():
                raise RepositoryCheckError(
                    f"broken local link in {document.relative_to(root)}: {raw}"
                )
            checked += 1
    return checked


def _lock_blocks(text: str) -> list[str]:
    lines = text.splitlines()
    blocks: list[str] = []
    current: list[str] = []
    for line in lines:
        if REQUIREMENT_RE.match(line):
            if current:
                blocks.append("\n".join(current))
            current = [line]
        elif current:
            if line and not line[0].isspace() and not line.startswith("#"):
                blocks.append("\n".join(current))
                current = []
            else:
                current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def check_dependency_locks(root: Path) -> dict[str, int]:
    result: dict[str, int] = {}
    for filename in ("requirements.lock", "requirements-dev.lock"):
        text = (root / filename).read_text(encoding="utf-8")
        blocks = _lock_blocks(text)
        if not blocks:
            raise RepositoryCheckError(f"{filename} has no pinned distributions")
        missing_hash = [block.splitlines()[0] for block in blocks if "--hash=sha256:" not in block]
        if missing_hash:
            raise RepositoryCheckError(f"{filename} has unhashed distributions: {missing_hash}")
        result[filename] = len(blocks)

    for filename in ("requirements.in", "requirements-dev.in"):
        for line in (root / filename).read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "-r ")):
                continue
            if REQUIREMENT_RE.fullmatch(stripped) is None:
                raise RepositoryCheckError(f"unbounded direct input in {filename}: {stripped}")
    return result


def action_inventory(root: Path) -> list[dict[str, str]]:
    workflow_root = root / ".github/workflows"
    observed = {path.name for path in workflow_root.glob("*.yml")}
    missing = sorted(REQUIRED_WORKFLOWS - observed)
    if missing:
        raise RepositoryCheckError(f"missing required workflows: {missing}")

    inventory: list[dict[str, str]] = []
    for workflow in sorted(workflow_root.glob("*.yml")):
        text = workflow.read_text(encoding="utf-8")
        if "pull_request_target:" in text:
            raise RepositoryCheckError(f"{workflow.name} may not use pull_request_target")
        if "permissions:" not in text:
            raise RepositoryCheckError(f"{workflow.name} must declare permissions")
        if "actions/checkout" in text and "persist-credentials: false" not in text:
            raise RepositoryCheckError(f"{workflow.name} must disable persisted Git credentials")
        if re.search(r"(?m)^\s*(?:image|container):\s*[^\n]+:latest\s*$", text):
            raise RepositoryCheckError(f"{workflow.name} contains a mutable Docker tag")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if "uses:" not in line or "uses: ./" in line:
                continue
            match = ACTION_RE.match(line)
            if match is None:
                raise RepositoryCheckError(
                    f"{workflow.name}:{line_number} action is not pinned with a version comment"
                )
            sha = match.group("sha")
            if LOWER_SHA_RE.fullmatch(sha) is None:
                raise RepositoryCheckError(f"invalid action SHA in {workflow.name}:{line_number}")
            inventory.append(
                {
                    "action": match.group("action"),
                    "release": match.group("version"),
                    "sha": sha,
                    "workflow": workflow.name,
                }
            )
    if not inventory:
        raise RepositoryCheckError("workflow action inventory is empty")
    return inventory


def check_hygiene(root: Path) -> None:
    gitignore = (root / ".gitignore").read_text(encoding="utf-8")
    for required in (".venv/", "dist/", "/release/", ".env", ".coverage"):
        if required not in gitignore:
            raise RepositoryCheckError(f".gitignore is missing {required}")

    git = shutil.which("git")
    if git is None:
        raise RepositoryCheckError("git is required for repository hygiene validation")
    listed = subprocess.run(  # noqa: S603 - fixed Git argv; no user input
        [git, "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    forbidden = (
        re.compile("/" + "Users" + r"/[^\s]+"),
        re.compile(r"[A-Za-z]:\\\\" + "Users" + r"\\\\"),
    )
    for relative in sorted(listed.stdout.splitlines()):
        path = root / relative
        if not path.is_file():
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".whl"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if path.as_posix().endswith("tests/unit/test_security_models.py"):
            continue
        if any(pattern.search(text) for pattern in forbidden):
            raise RepositoryCheckError(
                f"developer-local absolute path found in {path.relative_to(root)}"
            )


def validate_repository(root: Path) -> dict[str, Any]:
    check_required_files(root)
    version = check_version_contract(root)
    phase1_audit = check_phase1_audit_readiness(root)
    link_count = check_local_links(root)
    locks = check_dependency_locks(root)
    actions = action_inventory(root)
    check_hygiene(root)
    return {
        "action_references": actions,
        "local_links_checked": link_count,
        "lock_distribution_counts": locks,
        "phase1_audit": phase1_audit,
        "status": "passed",
        "version": version,
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        result = validate_repository(root)
    except RepositoryCheckError as error:
        print(f"repository validation failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
