#!/usr/bin/env python3
"""Enforce branch-aware combined coverage across every governance-critical namespace."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Final

CRITICAL_ROOTS: Final = (
    "src/quantforge/audit/",
    "src/quantforge/domain/",
    "src/quantforge/engine/",
    "src/quantforge/evidence/",
    "src/quantforge/roles/",
    "src/quantforge/serialization/",
    "src/quantforge/storage/",
    "src/quantforge/verdict/",
    "src/quantforge/workflow/",
)


def critical_coverage(path: Path) -> tuple[float, int, int]:
    value: Any = json.loads(path.read_text(encoding="utf-8"))
    files = value.get("files") if isinstance(value, dict) else None
    if not isinstance(files, dict):
        raise ValueError("coverage JSON lacks its file inventory")
    matched_roots: set[str] = set()
    covered = 0
    measured = 0
    for name, details in files.items():
        if not isinstance(name, str) or not isinstance(details, dict):
            raise ValueError("coverage JSON contains a malformed file record")
        root = next((prefix for prefix in CRITICAL_ROOTS if name.startswith(prefix)), None)
        if root is None:
            continue
        matched_roots.add(root)
        summary = details.get("summary")
        if not isinstance(summary, dict):
            raise ValueError("coverage JSON lacks a branch-aware file summary")
        covered_lines = summary.get("covered_lines")
        num_statements = summary.get("num_statements")
        covered_branches = summary.get("covered_branches")
        num_branches = summary.get("num_branches")
        if not all(
            isinstance(item, int)
            for item in (covered_lines, num_statements, covered_branches, num_branches)
        ):
            raise ValueError("coverage JSON lacks statement or branch measurements")
        assert isinstance(covered_lines, int)
        assert isinstance(num_statements, int)
        assert isinstance(covered_branches, int)
        assert isinstance(num_branches, int)
        covered += covered_lines + covered_branches
        measured += num_statements + num_branches
    missing = sorted(set(CRITICAL_ROOTS).difference(matched_roots))
    if missing:
        raise ValueError(f"coverage omitted governance-critical namespaces: {missing}")
    if measured < 1:
        raise ValueError("governance-critical coverage has no measured paths")
    return covered * 100 / measured, covered, measured


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coverage-json", type=Path, required=True)
    parser.add_argument("--minimum", type=float, default=90.0)
    args = parser.parse_args()
    percent, covered, measured = critical_coverage(args.coverage_json)
    print(f"governance-critical combined branch coverage: {percent:.2f}% ({covered}/{measured})")
    if percent + 1e-12 < args.minimum:
        raise SystemExit(
            f"governance-critical coverage {percent:.2f}% is below {args.minimum:.2f}%"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
