from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from quantforge.audit import AuditLog
from quantforge.engine import LocalCppV1Adapter
from quantforge.evidence.bundle import CPP_PEELED_TARGET, CPP_RELEASE, CPP_TAG_OBJECT
from quantforge.serialization.canonical import canonical_json
from quantforge.storage import (
    SQLiteCaseStore,
    execute_and_admit_engine_evidence,
    persist_audited_case,
)
from quantforge.workflow.demo import run_demo


def _integration_path(name: str) -> Path:
    value = os.environ.get(name)
    if value is None:
        pytest.skip("the immutable C++ v1.0.0 integration fixture is not configured")
    return Path(value)


def test_immutable_cpp_v1_fixture_is_admitted_deterministically(tmp_path: Path) -> None:
    repository = _integration_path("QUANTFORGE_CPP_V1_REPOSITORY")
    executable = _integration_path("QUANTFORGE_CPP_V1_EXECUTABLE")
    work_root = _integration_path("QUANTFORGE_CPP_V1_WORK_ROOT")
    executable_digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    adapter = LocalCppV1Adapter(
        repository=repository,
        executable=executable,
        expected_executable_sha256=executable_digest,
        work_root=work_root,
    )

    identity = adapter.verify_release_identity()
    assert identity.release == CPP_RELEASE
    assert identity.annotated_tag_object == CPP_TAG_OBJECT
    assert identity.peeled_target == CPP_PEELED_TARGET
    assert identity.executable_sha256 == executable_digest

    first = adapter.execute_approved_fixture()
    second = adapter.execute_approved_fixture()
    assert canonical_json(first.output_semantics) == canonical_json(second.output_semantics)
    assert canonical_json(first.numeric_facts) == canonical_json(second.numeric_facts)
    assert canonical_json(first.validators) == canonical_json(second.validators)
    assert first.configuration_sha256 == second.configuration_sha256
    assert first.input_semantics == second.input_semantics
    assert first.numeric_facts[0].methodology_id == "causal_daily_v3_stochastic_v2"
    assert first.output_root.is_relative_to(work_root)
    assert second.output_root.is_relative_to(work_root)
    assert not (repository / "results").exists()

    demo = run_demo("provisional")
    store = SQLiteCaseStore(tmp_path / "trusted-admission.sqlite3")
    store.initialize()
    persist_audited_case(store, AuditLog(demo.audit_log.events[:5]))
    admitted = execute_and_admit_engine_evidence(
        store,
        adapter,
        case_id="case_provisional",
        evidence_id="evidence_cpp_v1_integration",
    )
    assert admitted.durable_case.revision == 6
    assert admitted.durable_case.evidence_ledger is not None
    assert store.verify().bundle_count == 1
