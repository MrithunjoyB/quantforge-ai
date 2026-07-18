#!/usr/bin/env python3
"""Small deterministic repository secret-pattern gate with no external dependency."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

PATTERNS = {
    "OpenAI-style secret": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "private key": re.compile(
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?(?:PRIVATE KEY|PRIVATE KEY BLOCK)-----"
    ),
}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".whl"}


def candidate_files(root: Path) -> list[Path]:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required for the repository secret scan")
    result = subprocess.run(  # noqa: S603 - fixed git argv; no user-supplied command
        [git, "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [root / line for line in result.stdout.splitlines() if line]


def history_text(root: Path) -> str:
    """Return textual patches for all reachable history without invoking a shell."""
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required for the repository secret scan")
    result = subprocess.run(  # noqa: S603 - fixed git argv; no user-supplied command
        [git, "log", "--all", "--full-history", "--no-ext-diff", "--text", "-p"],
        cwd=root,
        check=True,
        capture_output=True,
        encoding="latin-1",
    )
    return result.stdout


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    findings: list[str] = []
    for path in candidate_files(root):
        if not path.is_file() or path.suffix.lower() in SKIP_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{path.relative_to(root)}: possible {label}")
    history = history_text(root)
    for label, pattern in PATTERNS.items():
        if pattern.search(history):
            findings.append(f"reachable Git history: possible {label}")
    if findings:
        print("\n".join(findings), file=sys.stderr)
        return 1
    print("secret scan: current files and reachable history contain no known credential patterns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
