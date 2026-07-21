from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from quantforge.evaluation.models import evaluation_run_semantic_values
from quantforge.evaluation.persistence import (
    export_evaluation,
    replay_evaluation_export,
    verify_evaluation_export,
)
from quantforge.evaluation.runner import run_offline_evaluation
from quantforge.evaluation.suite import load_suite, select_cases
from quantforge.serialization.canonical import canonical_json, canonical_sha256


def _one_case_export(root: Path) -> tuple[Path, object]:
    suite = load_suite()
    cases = select_cases(suite, benchmark_id="qf-bm-020-verdict-upgrade")
    run = run_offline_evaluation(suite, cases, subset="single_case")
    output = root / "evaluation-export"
    export_evaluation(run, suite, output)
    return output, run


def test_export_is_closed_byte_stable_verified_and_semantically_replayable(
    tmp_path: Path,
) -> None:
    first, run = _one_case_export(tmp_path / "first")
    second, repeated = _one_case_export(tmp_path / "second")

    assert run == repeated
    assert {path.name for path in first.iterdir()} == {
        "benchmark-inventory.json",
        "comparison-report.json",
        "comparison-report.md",
        "evidence-manifest.json",
        "export-manifest.json",
    }
    assert {path.name: path.read_bytes() for path in first.iterdir()} == {
        path.name: path.read_bytes() for path in second.iterdir()
    }
    verification = verify_evaluation_export(first)
    replay = replay_evaluation_export(first)
    assert verification["valid"] is True
    assert verification["result_count"] == 3
    assert replay["duplicate_transition_count"] == 0
    assert replay["durable_advancement_created"] is False
    assert len(replay["accepted_semantic_outputs"]) == 3
    assert "OFFLINE DETERMINISTIC EVALUATION" in (first / "comparison-report.md").read_text(
        encoding="utf-8"
    )


@pytest.mark.malicious
def test_export_rejects_simple_tampering_and_extra_artifacts(tmp_path: Path) -> None:
    output, _ = _one_case_export(tmp_path)
    report = output / "comparison-report.json"
    report.write_bytes(report.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        verify_evaluation_export(output)

    output, _ = _one_case_export(tmp_path / "extra")
    (output / "not-declared.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(ValueError, match="missing or extra"):
        verify_evaluation_export(output)


@pytest.mark.malicious
def test_rehashed_score_tampering_is_independently_recomputed_and_rejected(
    tmp_path: Path,
) -> None:
    output, _ = _one_case_export(tmp_path)
    report_path = output / "comparison-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["scores"][0]["detection_credit_earned"] = 0
    score_values = dict(report["scores"][0])
    score_values.pop("semantic_sha256")
    report["scores"][0]["semantic_sha256"] = canonical_sha256(score_values)
    report["semantic_sha256"] = canonical_sha256(evaluation_run_semantic_values(report))
    report_path.write_text(canonical_json(report), encoding="utf-8")

    manifest_path = output / "export-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["run_semantic_sha256"] = report["semantic_sha256"]
    manifest["artifacts"]["comparison-report.json"] = hashlib.sha256(
        report_path.read_bytes()
    ).hexdigest()
    manifest_values = dict(manifest)
    manifest_values.pop("manifest_sha256")
    manifest["manifest_sha256"] = canonical_sha256(manifest_values)
    manifest_path.write_text(canonical_json(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="scores do not recompute"):
        verify_evaluation_export(output)


def test_export_refuses_overwrite(tmp_path: Path) -> None:
    output, run = _one_case_export(tmp_path)
    with pytest.raises(ValueError, match="already exists"):
        export_evaluation(run, load_suite(), output)


@pytest.mark.malicious
def test_environment_credentials_never_enter_evaluation_exports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "sk" + "-evaluation-secret-that-must-not-appear"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    output, _ = _one_case_export(tmp_path)
    exported = b"".join(path.read_bytes() for path in sorted(output.iterdir()))
    assert secret.encode() not in exported
