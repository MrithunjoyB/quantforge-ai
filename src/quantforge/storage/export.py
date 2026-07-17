"""Deterministic durable-case packages with immutable export lineage."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from quantforge.audit import AuditLog
from quantforge.domain.models import Sha256, StrictModel, TribunalCase, WorkflowState
from quantforge.evidence.bundle import GENESIS_BUNDLE_HASH, EvidenceBundle, amendment_chain_hash
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
    schema_version: Literal["2.0"] = "2.0"
    export_id: str = Field(pattern=r"^export_[0-9a-f]{32}$")
    case_id: str
    workflow_revision: int = Field(ge=1)
    workflow_state: WorkflowState
    case_semantic_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    audit_head_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_chain_head: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    evidence_bundle_ids: dict[str, str]
    graph_present: bool
    graph_revision: int | None = Field(default=None, ge=1)
    graph_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    parent_export_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    complete: bool
    artifacts: dict[str, Sha256]

    @model_validator(mode="after")
    def graph_anchor_is_complete(self) -> CasePackageManifest:
        if self.graph_present != (self.graph_revision is not None and self.graph_hash is not None):
            raise ValueError("manifest claim-graph anchor is partial or contradictory")
        required = {"audit.jsonl", "case.json", "evidence_bundles.json"}
        permitted = required | {"claim_graph.json", "evidence_ledger.json"}
        artifact_names = set(self.artifacts)
        if not required.issubset(artifact_names) or not artifact_names.issubset(permitted):
            raise ValueError("manifest artifact inventory is outside the package contract")
        if self.graph_present != ("claim_graph.json" in artifact_names):
            raise ValueError("manifest graph declaration contradicts its artifact inventory")
        if bool(self.evidence_ids) != ("evidence_ledger.json" in artifact_names):
            raise ValueError("manifest evidence declaration contradicts its artifact inventory")
        return self


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
    if durable.claim_graph is not None and durable.graph_revision != durable.revision:
        raise ValueError("exports require a claim graph anchored at the exported revision")
    bundle_ids = tuple(bundle.semantic.bundle_id for bundle in bundles)
    evidence_ids = durable.case.evidence_ids
    evidence_bundle_ids = _evidence_bundle_relationships(durable.evidence_ledger)
    export_id = _export_id(
        case_id=case_id,
        workflow_revision=durable.revision,
        case_semantic_hash=durable.semantic_hash,
        audit_head_hash=durable.audit_head_hash,
        graph_revision=durable.graph_revision,
        graph_hash=durable.graph_hash,
        bundle_chain_head=bundles[-1].bundle_hash if bundles else GENESIS_BUNDLE_HASH,
        bundle_ids=bundle_ids,
        evidence_ids=evidence_ids,
        evidence_bundle_ids=evidence_bundle_ids,
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
        bundle_ids=bundle_ids,
        evidence_ids=evidence_ids,
        evidence_bundle_ids=evidence_bundle_ids,
        graph_present=durable.claim_graph is not None,
        graph_revision=durable.graph_revision,
        graph_hash=durable.graph_hash,
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
    try:
        store.record_export(
            case_id,
            record,
            expected_revision=durable.revision,
            created_at=durable.audit_log.events[-1].timestamp,
        )
    except BaseException:
        shutil.rmtree(output_directory.absolute())
        raise
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
        if candidate.is_dir():
            continue
        if not candidate.is_file():
            raise ValueError("case package contains an unexpected filesystem entry")
        actual_files.add(candidate.relative_to(directory).as_posix())
    if actual_files != expected_files:
        raise ValueError("case package file inventory is missing, extra, or substituted")
    for name, expected_hash in manifest.artifacts.items():
        actual_hash = hashlib.sha256((directory / name).read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            raise ValueError(f"case package artifact hash mismatch: {name}")
    case_value = safe_load_json(directory / "case.json")
    case = TribunalCase.model_validate_json(canonical_json(case_value))
    audit = AuditLog.read_jsonl(directory / "audit.jsonl", require_complete=False)
    replayed = audit.replay_case(require_complete=False)
    complete = replayed.state is WorkflowState.CHAIR_EXPLANATION
    if replayed != case:
        raise ValueError("case package snapshot does not match semantic audit replay")
    if manifest.case_id != case.case_id:
        raise ValueError("case package manifest has a foreign case identifier")
    if manifest.workflow_revision != len(audit.events):
        raise ValueError("case package workflow revision contradicts its audit")
    if manifest.workflow_state is not case.state:
        raise ValueError("case package workflow state contradicts its audit")
    if manifest.complete != complete:
        raise ValueError("case package completeness contradicts terminal workflow policy")
    if complete:
        audit.verify(require_complete=True)
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
    if manifest.evidence_ids != case.evidence_ids:
        raise ValueError("case package evidence declaration contradicts its case")
    graph_path = directory / "claim_graph.json"
    graph_present = graph_path.exists()
    graph_hash: str | None = None
    if graph_present:
        if ledger is None:
            raise ValueError("case package claim graph exists without evidence")
        graph_value = safe_load_json(graph_path)
        graph_snapshot = ClaimGraphSnapshot.model_validate_json(canonical_json(graph_value))
        graph = ClaimGraph.from_snapshot(graph_snapshot)
        graph.validate_against_ledger(ledger)
        graph.validate_final_claim_traceability()
        graph_hash = canonical_sha256(graph_snapshot)
    if graph_present != manifest.graph_present:
        raise ValueError("case package graph declaration contradicts its files")
    if complete and not graph_present:
        raise ValueError("complete case package requires a claim graph")
    expected_graph_revision = len(audit.events) if graph_present else None
    if manifest.graph_revision != expected_graph_revision or manifest.graph_hash != graph_hash:
        raise ValueError("case package graph anchor contradicts its graph")
    bundle_value = safe_load_json(directory / "evidence_bundles.json")
    if not isinstance(bundle_value, list):
        raise ValueError("case package evidence bundle inventory must be a list")
    bundles = tuple(
        EvidenceBundle.model_validate_json(canonical_json(item)) for item in bundle_value
    )
    previous = GENESIS_BUNDLE_HASH
    execution_events = [
        event for event in audit.events if event.workflow_state is WorkflowState.EXPERIMENT_EXECUTED
    ]
    expected_bundle_revision = (
        execution_events[0].sequence - 1 if len(execution_events) == 1 else None
    )
    for bundle in bundles:
        if (
            bundle.semantic.case_id != case.case_id
            or bundle.semantic.previous_bundle_hash != previous
            or bundle.semantic.workflow_revision != expected_bundle_revision
            or case.constitution is None
            or bundle.semantic.constitution_id != case.constitution.constitution_id
            or bundle.semantic.constitution_hash != case.constitution.constitution_hash
            or bundle.semantic.amendment_chain_hash != amendment_chain_hash(case.amendments)
        ):
            raise ValueError("case package evidence-bundle chain mismatch")
        previous = bundle.bundle_hash
    if previous != manifest.bundle_chain_head:
        raise ValueError("case package evidence-bundle head mismatch")
    bundle_ids = tuple(bundle.semantic.bundle_id for bundle in bundles)
    if bundle_ids != manifest.bundle_ids:
        raise ValueError("case package evidence-bundle declaration mismatch")
    relationships = _evidence_bundle_relationships(ledger)
    if relationships != manifest.evidence_bundle_ids:
        raise ValueError("case package evidence-to-bundle relationships mismatch")
    bundle_by_id = {bundle.semantic.bundle_id: bundle for bundle in bundles}
    if len(bundle_by_id) != len(bundles) or set(relationships.values()) != set(bundle_by_id):
        raise ValueError("case package contains an orphan or duplicate evidence bundle")
    if ledger is not None:
        for evidence in ledger.snapshot().evidence:
            if evidence.source_adapter != "cpp_v1_adapter":
                continue
            bundle_id = relationships[evidence.evidence_id]
            bundle = bundle_by_id[bundle_id]
            output_hashes = {
                item.path: item.byte_sha256 for item in bundle.observations.output_artifacts
            }
            if (
                evidence.provenance.get("bundle_hash") != bundle.bundle_hash
                or evidence.content.get("bundle_hash") != bundle.bundle_hash
                or evidence.content.get("semantic_hash") != bundle.semantic_hash
                or output_hashes.get(evidence.source_artifact) != evidence.source_artifact_sha256
            ):
                raise ValueError("case package engine evidence provenance mismatch")
    expected_export_id = _export_id(
        case_id=case.case_id,
        workflow_revision=len(audit.events),
        case_semantic_hash=canonical_sha256(case),
        audit_head_hash=audit.events[-1].current_event_hash,
        graph_revision=expected_graph_revision,
        graph_hash=graph_hash,
        bundle_chain_head=previous,
        bundle_ids=bundle_ids,
        evidence_ids=case.evidence_ids,
        evidence_bundle_ids=relationships,
    )
    if manifest.export_id != expected_export_id:
        raise ValueError("case package export identifier is not reproducible")
    return {
        "case_id": case.case_id,
        "complete": manifest.complete,
        "export_id": manifest.export_id,
        "manifest_hash": canonical_sha256(manifest),
        "revision": len(audit.events),
        "valid": True,
    }


def _evidence_bundle_relationships(ledger: EvidenceLedger | None) -> dict[str, str]:
    if ledger is None:
        return {}
    relationships: dict[str, str] = {}
    for evidence in ledger.snapshot().evidence:
        bundle_id = evidence.provenance.get("bundle_id")
        if evidence.source_adapter == "cpp_v1_adapter":
            if not isinstance(bundle_id, str):
                raise ValueError("engine evidence lacks its bundle relationship")
            relationships[evidence.evidence_id] = bundle_id
        elif bundle_id is not None:
            raise ValueError("non-engine evidence declares an unauthorized engine bundle")
    return dict(sorted(relationships.items()))


def _export_id(
    *,
    case_id: str,
    workflow_revision: int,
    case_semantic_hash: str,
    audit_head_hash: str,
    graph_revision: int | None,
    graph_hash: str | None,
    bundle_chain_head: str,
    bundle_ids: tuple[str, ...],
    evidence_ids: tuple[str, ...],
    evidence_bundle_ids: dict[str, str],
) -> str:
    """Derive export identity from authoritative semantic and lineage anchors."""

    identity = {
        "audit_head_hash": audit_head_hash,
        "bundle_chain_head": bundle_chain_head,
        "bundle_ids": bundle_ids,
        "case_id": case_id,
        "case_semantic_hash": case_semantic_hash,
        "evidence_bundle_ids": evidence_bundle_ids,
        "evidence_ids": evidence_ids,
        "graph_hash": graph_hash,
        "graph_revision": graph_revision,
        "workflow_revision": workflow_revision,
    }
    return f"export_{canonical_sha256(identity)[:32]}"


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
