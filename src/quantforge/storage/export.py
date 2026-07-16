"""Deterministic durable-case packages with immutable export lineage."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from quantforge.audit import AuditLog
from quantforge.domain.models import StrictModel, TribunalCase, WorkflowState
from quantforge.evidence.bundle import GENESIS_BUNDLE_HASH, EvidenceBundle
from quantforge.evidence.graph import ClaimGraph, ClaimGraphSnapshot
from quantforge.evidence.ledger import EvidenceLedger, EvidenceLedgerSnapshot
from quantforge.serialization.canonical import canonical_json, canonical_sha256
from quantforge.serialization.safe_json import (
    reject_symlink_components,
    safe_load_json,
    safe_write_text,
)
from quantforge.storage.base import CaseStore, ExportRecord


class CasePackageManifest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    export_id: str = Field(pattern=r"^export_[0-9a-f]{32}$")
    case_id: str
    workflow_revision: int = Field(ge=1)
    workflow_state: WorkflowState
    case_semantic_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    audit_head_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_chain_head: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_export_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    complete: bool
    artifacts: dict[str, str]


@dataclass(frozen=True)
class CaseExportResult:
    output_directory: Path
    export_id: str
    manifest_hash: str
    artifact_hashes: tuple[tuple[str, str], ...]


def export_durable_case(
    store: CaseStore,
    case_id: str,
    output_directory: Path,
) -> CaseExportResult:
    """Export byte-stable semantic state; no wall-clock field enters the package."""

    durable = store.reconstruct(case_id, require_complete=False)
    bundles = store.list_evidence_bundles(case_id)
    export_id = (
        f"export_{canonical_sha256({'case_id': case_id, 'revision': durable.revision})[:32]}"
    )
    existing = store.find_export(case_id, export_id)
    latest = store.latest_export(case_id)
    parent = (
        existing.parent_manifest_hash
        if existing is not None
        else latest.manifest_hash
        if latest is not None
        else GENESIS_BUNDLE_HASH
    )
    texts: dict[str, str] = {
        "audit.jsonl": "".join(canonical_json(event) + "\n" for event in durable.audit_log.events),
        "case.json": canonical_json(durable.case) + "\n",
        "evidence_bundles.json": canonical_json(bundles) + "\n",
    }
    if durable.evidence_ledger is not None:
        texts["evidence_ledger.json"] = canonical_json(durable.evidence_ledger.snapshot()) + "\n"
    if durable.claim_graph is not None:
        texts["claim_graph.json"] = canonical_json(durable.claim_graph.snapshot()) + "\n"
    artifact_hashes = {
        name: hashlib.sha256(value.encode("utf-8")).hexdigest()
        for name, value in sorted(texts.items())
    }
    manifest = CasePackageManifest(
        export_id=export_id,
        case_id=case_id,
        workflow_revision=durable.revision,
        workflow_state=durable.case.state,
        case_semantic_hash=durable.semantic_hash,
        audit_head_hash=durable.audit_head_hash,
        bundle_chain_head=bundles[-1].bundle_hash if bundles else GENESIS_BUNDLE_HASH,
        parent_export_manifest_hash=parent,
        complete=durable.case.state is WorkflowState.CHAIR_EXPLANATION,
        artifacts=artifact_hashes,
    )
    manifest_hash = canonical_sha256(manifest)
    record = ExportRecord(
        export_id=export_id,
        revision=durable.revision,
        parent_manifest_hash=parent,
        manifest_json=canonical_json(manifest),
        manifest_hash=manifest_hash,
        artifact_hashes=tuple(sorted(artifact_hashes.items())),
    )
    if existing is not None and existing != record:
        raise ValueError("deterministic export differs from its immutable durable record")
    _write_package(output_directory, texts, manifest)
    store.record_export(
        case_id,
        record,
        expected_revision=durable.revision,
        created_at=durable.audit_log.events[-1].timestamp,
    )
    return CaseExportResult(
        output_directory=output_directory.absolute(),
        export_id=export_id,
        manifest_hash=manifest_hash,
        artifact_hashes=record.artifact_hashes,
    )


def verify_case_package(directory: Path) -> dict[str, Any]:
    """Independently reconstruct and cross-check an exported durable case package."""

    reject_symlink_components(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("case package must be a regular non-symlink directory")
    manifest_value = safe_load_json(directory / "case_package_manifest.json")
    manifest = CasePackageManifest.model_validate_json(canonical_json(manifest_value))
    expected_files = {*manifest.artifacts, "case_package_manifest.json"}
    actual_files: set[str] = set()
    for candidate in sorted(directory.rglob("*")):
        if candidate.is_symlink():
            raise ValueError("case package contains a symlink")
        if candidate.is_file():
            actual_files.add(candidate.relative_to(directory).as_posix())
    if actual_files != expected_files:
        raise ValueError("case package file inventory is missing, extra, or substituted")
    for name, expected_hash in manifest.artifacts.items():
        actual_hash = hashlib.sha256((directory / name).read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            raise ValueError(f"case package artifact hash mismatch: {name}")
    case_value = safe_load_json(directory / "case.json")
    case = TribunalCase.model_validate_json(canonical_json(case_value))
    audit = AuditLog.read_jsonl(directory / "audit.jsonl", require_complete=manifest.complete)
    if audit.replay_case(require_complete=manifest.complete) != case:
        raise ValueError("case package snapshot does not match semantic audit replay")
    if canonical_sha256(case) != manifest.case_semantic_hash:
        raise ValueError("case package semantic hash mismatch")
    if audit.events[-1].current_event_hash != manifest.audit_head_hash:
        raise ValueError("case package audit head mismatch")
    ledger: EvidenceLedger | None = None
    ledger_path = directory / "evidence_ledger.json"
    if ledger_path.exists():
        snapshot_value = safe_load_json(ledger_path)
        snapshot = EvidenceLedgerSnapshot.model_validate_json(canonical_json(snapshot_value))
        ledger = EvidenceLedger.from_snapshot(snapshot, claim_ids={case.claim.claim_id})
        if tuple(item.evidence_id for item in snapshot.evidence) != case.evidence_ids:
            raise ValueError("case package evidence ledger does not match the case")
    elif case.evidence_ids:
        raise ValueError("case package omits its durable evidence ledger")
    graph_path = directory / "claim_graph.json"
    if graph_path.exists():
        if ledger is None:
            raise ValueError("case package claim graph exists without evidence")
        graph_value = safe_load_json(graph_path)
        graph_snapshot = ClaimGraphSnapshot.model_validate_json(canonical_json(graph_value))
        graph = ClaimGraph.from_snapshot(graph_snapshot)
        graph.validate_against_ledger(ledger)
        graph.validate_final_claim_traceability()
    bundle_value = safe_load_json(directory / "evidence_bundles.json")
    if not isinstance(bundle_value, list):
        raise ValueError("case package evidence bundle inventory must be a list")
    bundles = tuple(
        EvidenceBundle.model_validate_json(canonical_json(item)) for item in bundle_value
    )
    previous = GENESIS_BUNDLE_HASH
    for bundle in bundles:
        if (
            bundle.semantic.case_id != case.case_id
            or bundle.semantic.previous_bundle_hash != previous
        ):
            raise ValueError("case package evidence-bundle chain mismatch")
        previous = bundle.bundle_hash
    if previous != manifest.bundle_chain_head:
        raise ValueError("case package evidence-bundle head mismatch")
    return {
        "case_id": case.case_id,
        "complete": manifest.complete,
        "export_id": manifest.export_id,
        "manifest_hash": canonical_sha256(manifest),
        "revision": len(audit.events),
        "valid": True,
    }


def _write_package(
    output_directory: Path,
    texts: dict[str, str],
    manifest: CasePackageManifest,
) -> None:
    output = output_directory.absolute()
    reject_symlink_components(output.parent)
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    reject_symlink_components(output)
    if output.exists():
        raise ValueError("case package output already exists")
    with tempfile.TemporaryDirectory(prefix=".quantforge-export-", dir=output.parent) as temporary:
        package = Path(temporary) / "package"
        package.mkdir(mode=0o700)
        for name, value in sorted(texts.items()):
            safe_write_text(package / name, value)
        safe_write_text(
            package / "case_package_manifest.json",
            canonical_json(manifest) + "\n",
        )
        os.replace(package, output)


__all__ = [
    "CaseExportResult",
    "CasePackageManifest",
    "export_durable_case",
    "verify_case_package",
]
