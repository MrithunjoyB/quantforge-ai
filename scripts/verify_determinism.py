#!/usr/bin/env python3
"""Prove byte, hash, audit-replay, and verdict stability for all synthetic scenarios."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

SCENARIOS = ("fragile", "inconclusive", "provisional")
ARTIFACTS = (
    "audit.jsonl",
    "bundle_manifest.json",
    "case.json",
    "claim_graph.json",
    "evidence_ledger.json",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_all(work_dir: Path) -> dict[str, Any]:
    """Run each scenario twice into a new directory and compare every governed artifact."""
    from quantforge import __version__
    from quantforge.audit import AuditLog
    from quantforge.serialization.export import export_demo
    from quantforge.workflow.demo import run_demo

    work_dir.mkdir(parents=True, exist_ok=False)
    comparisons = 0
    scenario_reports: dict[str, Any] = {}
    for scenario in SCENARIOS:
        first_result = run_demo(scenario)
        second_result = run_demo(scenario)
        first = work_dir / scenario / "first"
        second = work_dir / scenario / "second"
        first_hashes = export_demo(first_result, first)
        second_hashes = export_demo(second_result, second)
        if first_hashes != second_hashes:
            raise RuntimeError(f"{scenario} canonical hash inventories differ")

        file_hashes: dict[str, str] = {}
        for name in ARTIFACTS:
            first_bytes = (first / name).read_bytes()
            second_bytes = (second / name).read_bytes()
            if first_bytes != second_bytes:
                raise RuntimeError(f"{scenario}/{name} is not byte-identical")
            file_hashes[name] = hashlib.sha256(first_bytes).hexdigest()
            comparisons += 1

        first_log = AuditLog.read_jsonl(first / "audit.jsonl")
        second_log = AuditLog.read_jsonl(second / "audit.jsonl")
        if first_log.replay_case() != first_result.case:
            raise RuntimeError(f"{scenario} first audit does not replay to its case")
        if second_log.replay_case() != second_result.case:
            raise RuntimeError(f"{scenario} second audit does not replay to its case")
        first_eligibility = first_result.case.verdict_eligibility
        second_eligibility = second_result.case.verdict_eligibility
        if first_eligibility is None or second_eligibility is None:
            raise RuntimeError(f"{scenario} did not produce verdict eligibility")
        if first_eligibility.verdict is not second_eligibility.verdict:
            raise RuntimeError(f"{scenario} verdict is unstable")

        scenario_reports[scenario] = {
            "audit_replay": "passed",
            "canonical_hashes": dict(sorted(first_hashes.items())),
            "file_sha256": dict(sorted(file_hashes.items())),
            "verdict": first_eligibility.verdict.value,
        }

    return {
        "artifact_comparisons": comparisons,
        "byte_identical": True,
        "scenarios": scenario_reports,
        "schema_version": "1.0",
        "semantic_audit_replay": "passed",
        "status": "passed",
        "verdict_stability": "passed",
        "version": __version__,
    }


def write_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = verify_all(args.work_dir)
        write_report(report, args.report)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"determinism validation failed: {error}", file=sys.stderr)
        return 1
    print(
        f"determinism: {report['artifact_comparisons']} byte-identical artifact comparisons; "
        "audit replay and verdict stability passed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
