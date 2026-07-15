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
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
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
    if findings:
        print("\n".join(findings), file=sys.stderr)
        return 1
    print("secret scan: no known credential patterns found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
