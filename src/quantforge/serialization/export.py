"""Complete deterministic case-bundle export."""

from __future__ import annotations

from pathlib import Path

from quantforge.serialization.canonical import canonical_sha256
from quantforge.serialization.safe_json import safe_write_json
from quantforge.workflow.demo import DemoResult


def export_demo(result: DemoResult, output_directory: Path) -> dict[str, str]:
    if output_directory.exists() and output_directory.is_symlink():
        raise ValueError("output directory cannot be a symlink")
    output_directory.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "case.json": result.case,
        "claim_graph.json": result.claim_graph.snapshot(),
        "evidence_ledger.json": result.evidence_ledger.snapshot(),
    }
    hashes: dict[str, str] = {}
    for name, value in artifacts.items():
        safe_write_json(output_directory / name, value)
        hashes[name] = canonical_sha256(value)
    result.audit_log.write_jsonl(output_directory / "audit.jsonl")
    hashes["audit.jsonl"] = canonical_sha256(result.audit_log.events)
    manifest = {
        "schema_version": "1.0",
        "case_id": result.case.case_id,
        "artifacts": hashes,
        "classification": "synthetic_validation_only",
    }
    safe_write_json(output_directory / "bundle_manifest.json", manifest)
    return hashes
