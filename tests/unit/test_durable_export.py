from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from quantforge.audit import AuditLog
from quantforge.serialization.canonical import canonical_json
from quantforge.serialization.safe_json import safe_load_json
from quantforge.storage import (
    SQLiteCaseStore,
    export_durable_case,
    persist_audited_case,
    verify_case_package,
)
from quantforge.workflow.demo import run_demo


def _file_hashes(directory: Path) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.iterdir())
    }


def test_repeated_exports_are_byte_identical_and_independently_reconstruct(
    tmp_path: Path,
) -> None:
    result = run_demo("provisional")
    store = SQLiteCaseStore(tmp_path / "cases.sqlite3")
    store.initialize()
    persist_audited_case(store, result.audit_log, claim_graph=result.claim_graph)
    first = export_durable_case(store, result.case.case_id, tmp_path / "first")
    second = export_durable_case(store, result.case.case_id, tmp_path / "second")
    assert first.export_id == second.export_id
    assert first.manifest_hash == second.manifest_hash
    assert _file_hashes(tmp_path / "first") == _file_hashes(tmp_path / "second")
    assert b"\r\n" not in (tmp_path / "first/audit.jsonl").read_bytes()
    verified = verify_case_package(tmp_path / "first")
    assert verified["valid"] is True
    assert verified["revision"] == 12
    assert store.inspect().export_count == 1


def test_export_lineage_advances_only_when_revision_advances(tmp_path: Path) -> None:
    result = run_demo("fragile")
    store = SQLiteCaseStore(tmp_path / "cases.sqlite3")
    store.initialize()
    prefix = AuditLog(result.audit_log.events[:5])
    persist_audited_case(store, prefix)
    first = export_durable_case(store, result.case.case_id, tmp_path / "prefix")
    assert verify_case_package(tmp_path / "prefix")["complete"] is False

    for revision, event in enumerate(result.audit_log.events[5:], start=5):
        store.append_event(event, expected_revision=revision)
    store.save_claim_graph(result.case.case_id, result.claim_graph, expected_revision=12)
    second = export_durable_case(store, result.case.case_id, tmp_path / "complete")
    manifest = safe_load_json(tmp_path / "complete/case_package_manifest.json")
    assert manifest["parent_export_manifest_hash"] == first.manifest_hash
    assert second.manifest_hash != first.manifest_hash
    assert store.inspect().export_count == 2
    store.verify()


def test_package_missing_extra_substituted_and_symlink_files_fail_closed(
    tmp_path: Path,
) -> None:
    result = run_demo("inconclusive")
    store = SQLiteCaseStore(tmp_path / "cases.sqlite3")
    store.initialize()
    persist_audited_case(store, result.audit_log, claim_graph=result.claim_graph)

    export_durable_case(store, result.case.case_id, tmp_path / "missing")
    (tmp_path / "missing/case.json").unlink()
    with pytest.raises(ValueError, match="inventory"):
        verify_case_package(tmp_path / "missing")

    export_durable_case(store, result.case.case_id, tmp_path / "extra")
    (tmp_path / "extra/unexpected.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="inventory"):
        verify_case_package(tmp_path / "extra")

    export_durable_case(store, result.case.case_id, tmp_path / "changed")
    (tmp_path / "changed/case.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_case_package(tmp_path / "changed")

    export_durable_case(store, result.case.case_id, tmp_path / "linked")
    target = tmp_path / "target"
    target.write_text("x", encoding="utf-8")
    (tmp_path / "linked/link").symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        verify_case_package(tmp_path / "linked")

    export_durable_case(store, result.case.case_id, tmp_path / "declared-extra")
    extra = tmp_path / "declared-extra/unexpected.json"
    extra.write_text("{}", encoding="utf-8")
    manifest_path = tmp_path / "declared-extra/case_package_manifest.json"
    manifest = safe_load_json(manifest_path)
    manifest["artifacts"][extra.name] = hashlib.sha256(extra.read_bytes()).hexdigest()
    manifest_path.write_text(canonical_json(manifest) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="outside the package contract"):
        verify_case_package(tmp_path / "declared-extra")


def test_graph_evidence_mismatch_is_detected_after_manifest_rehash(tmp_path: Path) -> None:
    result = run_demo("provisional")
    store = SQLiteCaseStore(tmp_path / "cases.sqlite3")
    store.initialize()
    persist_audited_case(store, result.audit_log, claim_graph=result.claim_graph)
    export_durable_case(store, result.case.case_id, tmp_path / "package")
    graph_path = tmp_path / "package/claim_graph.json"
    graph = safe_load_json(graph_path)
    evidence_node = next(node for node in graph["nodes"] if node["node_type"] == "evidence")
    evidence_node["evidence_sha256"] = "f" * 64
    graph_path.write_text(canonical_json(graph) + "\n", encoding="utf-8")
    manifest_path = tmp_path / "package/case_package_manifest.json"
    manifest = safe_load_json(manifest_path)
    manifest["artifacts"]["claim_graph.json"] = hashlib.sha256(graph_path.read_bytes()).hexdigest()
    manifest_path.write_text(canonical_json(manifest) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="graph evidence identity"):
        verify_case_package(tmp_path / "package")


@pytest.mark.parametrize(
    "field",
    [
        "case_id",
        "workflow_revision",
        "workflow_state",
        "complete",
        "export_id",
        "graph_declaration",
        "evidence_ids",
        "bundle_relationships",
        "case_semantic_hash",
        "audit_head_hash",
        "artifacts",
    ],
)
@pytest.mark.malicious
def test_contradictory_manifest_derived_claims_fail_closed(tmp_path: Path, field: str) -> None:
    result = run_demo("provisional")
    store = SQLiteCaseStore(tmp_path / "cases.sqlite3")
    store.initialize()
    persist_audited_case(store, result.audit_log, claim_graph=result.claim_graph)
    package = tmp_path / f"package-{field}"
    export_durable_case(store, result.case.case_id, package)
    manifest_path = package / "case_package_manifest.json"
    manifest = safe_load_json(manifest_path)
    if field == "case_id":
        manifest[field] = "case_substituted"
    elif field == "workflow_revision":
        manifest[field] = 11
    elif field == "workflow_state":
        manifest[field] = "VERDICT_ELIGIBILITY_COMPUTED"
    elif field == "complete":
        manifest[field] = False
    elif field == "export_id":
        manifest[field] = "export_" + "f" * 32
    elif field == "graph_declaration":
        manifest["graph_present"] = False
    elif field == "evidence_ids":
        manifest[field] = []
    elif field == "bundle_relationships":
        manifest["evidence_bundle_ids"] = {"evidence_provisional": "bundle_substituted"}
    elif field == "case_semantic_hash":
        manifest[field] = "a" * 64
    elif field == "audit_head_hash":
        manifest[field] = "b" * 64
    else:
        manifest[field]["case.json"] = "c" * 64
    manifest_path.write_text(canonical_json(manifest) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        verify_case_package(package)


def test_export_lineage_failure_removes_new_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_demo("fragile")
    store = SQLiteCaseStore(tmp_path / "cases.sqlite3")
    store.initialize()
    persist_audited_case(store, result.audit_log, claim_graph=result.claim_graph)

    def reject_record(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise ValueError("simulated lineage conflict")

    monkeypatch.setattr(store, "record_export", reject_record)
    output = tmp_path / "orphan-must-not-remain"
    with pytest.raises(ValueError, match="lineage conflict"):
        export_durable_case(store, result.case.case_id, output)
    assert not output.exists()


def test_export_output_and_lineage_are_immutable(tmp_path: Path) -> None:
    result = run_demo("fragile")
    store = SQLiteCaseStore(tmp_path / "cases.sqlite3")
    store.initialize()
    persist_audited_case(store, result.audit_log, claim_graph=result.claim_graph)
    output = tmp_path / "package"
    export_durable_case(store, result.case.case_id, output)
    with pytest.raises(ValueError, match="already exists"):
        export_durable_case(store, result.case.case_id, output)

    connection = sqlite3.connect(store.path)
    try:
        connection.execute(
            "UPDATE exports SET parent_manifest_hash = ? WHERE case_id = ?",
            ("f" * 64, result.case.case_id),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(ValueError, match="lineage"):
        store.verify()
