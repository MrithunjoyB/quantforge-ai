#!/usr/bin/env python3
"""Enforce branch-aware combined coverage across every governance-critical namespace."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Final

CRITICAL_ROOTS: Final = (
    "src/quantforge/audit/",
    "src/quantforge/cli/",
    "src/quantforge/domain/",
    "src/quantforge/engine/",
    "src/quantforge/evaluation/",
    "src/quantforge/evidence/",
    "src/quantforge/providers/",
    "src/quantforge/roles/",
    "src/quantforge/serialization/",
    "src/quantforge/storage/",
    "src/quantforge/verdict/",
    "src/quantforge/workflow/",
)

CRITICAL_FILES: Final = (
    "src/quantforge/providers/openai.py",
    "src/quantforge/roles/orchestrator.py",
)


def _summary_counts(name: str, details: object) -> tuple[int, int]:
    if not isinstance(details, dict):
        raise ValueError(f"coverage JSON contains a malformed file record: {name}")
    summary = details.get("summary")
    if not isinstance(summary, dict):
        raise ValueError(f"coverage JSON lacks a branch-aware file summary: {name}")
    values = (
        summary.get("covered_lines"),
        summary.get("num_statements"),
        summary.get("covered_branches"),
        summary.get("num_branches"),
    )
    if not all(isinstance(item, int) for item in values):
        raise ValueError(f"coverage JSON lacks statement or branch measurements: {name}")
    covered_lines, num_statements, covered_branches, num_branches = values
    assert isinstance(covered_lines, int)
    assert isinstance(num_statements, int)
    assert isinstance(covered_branches, int)
    assert isinstance(num_branches, int)
    return covered_lines + covered_branches, num_statements + num_branches


def critical_coverage(path: Path) -> tuple[float, int, int]:
    value: Any = json.loads(path.read_text(encoding="utf-8"))
    files = value.get("files") if isinstance(value, dict) else None
    if not isinstance(files, dict):
        raise ValueError("coverage JSON lacks its file inventory")
    matched_roots: set[str] = set()
    covered = 0
    measured = 0
    for name, details in files.items():
        if not isinstance(name, str):
            raise ValueError("coverage JSON contains a malformed file record")
        root = next((prefix for prefix in CRITICAL_ROOTS if name.startswith(prefix)), None)
        if root is None:
            continue
        matched_roots.add(root)
        file_covered, file_measured = _summary_counts(name, details)
        covered += file_covered
        measured += file_measured
    missing = sorted(set(CRITICAL_ROOTS).difference(matched_roots))
    if missing:
        raise ValueError(f"coverage omitted governance-critical namespaces: {missing}")
    if measured < 1:
        raise ValueError("governance-critical coverage has no measured paths")
    return covered * 100 / measured, covered, measured


def critical_file_coverage(path: Path) -> dict[str, tuple[float, int, int]]:
    value: Any = json.loads(path.read_text(encoding="utf-8"))
    files = value.get("files") if isinstance(value, dict) else None
    if not isinstance(files, dict):
        raise ValueError("coverage JSON lacks its file inventory")
    missing = sorted(set(CRITICAL_FILES).difference(files))
    if missing:
        raise ValueError(f"coverage omitted security-critical modules: {missing}")
    result: dict[str, tuple[float, int, int]] = {}
    for name in CRITICAL_FILES:
        covered, measured = _summary_counts(name, files[name])
        if measured < 1:
            raise ValueError(f"security-critical coverage has no measured paths: {name}")
        result[name] = (covered * 100 / measured, covered, measured)
    return result


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
    for name, (file_percent, file_covered, file_measured) in critical_file_coverage(
        args.coverage_json
    ).items():
        print(
            f"security-critical module coverage: {file_percent:.2f}% "
            f"({file_covered}/{file_measured}) {name}"
        )
        if file_percent + 1e-12 < args.minimum:
            raise SystemExit(
                f"security-critical module coverage {file_percent:.2f}% is below "
                f"{args.minimum:.2f}%: {name}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
