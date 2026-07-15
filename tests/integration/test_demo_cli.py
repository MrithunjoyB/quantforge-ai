from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from quantforge.cli.main import main
from quantforge.domain.models import Verdict
from quantforge.serialization.canonical import canonical_sha256
from quantforge.serialization.export import export_demo
from quantforge.serialization.safe_json import safe_load_json
from quantforge.workflow.demo import run_demo


@pytest.mark.parametrize(
    ("scenario", "verdict"),
    [
        ("provisional", Verdict.PROVISIONALLY_SUPPORTED),
        ("fragile", Verdict.FRAGILE),
        ("inconclusive", Verdict.INCONCLUSIVE),
    ],
)
def test_complete_demo_scenarios(scenario: str, verdict: Verdict, tmp_path: Path) -> None:
    result = run_demo(scenario)
    assert result.case.verdict_eligibility is not None
    assert result.case.verdict_eligibility.verdict is verdict
    output = tmp_path / scenario
    hashes = export_demo(result, output)
    assert set(hashes) == {
        "case.json",
        "claim_graph.json",
        "evidence_ledger.json",
        "audit.jsonl",
        "bundle_manifest.json",
    }
    assert (
        main(
            [
                "case",
                "validate",
                str(output / "case.json"),
                "--audit-file",
                str(output / "audit.jsonl"),
            ]
        )
        == 0
    )
    assert main(["case", "inspect", str(output / "case.json")]) == 0
    assert main(["audit", "verify", str(output / "audit.jsonl")]) == 0


def test_cli_run_demo_and_deterministic_repeated_exports(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    assert (
        main(
            [
                "case",
                "run-demo",
                "--scenario",
                "provisional",
                "--output-dir",
                str(first),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "case",
                "run-demo",
                "--scenario",
                "provisional",
                "--output-dir",
                str(second),
            ]
        )
        == 0
    )
    for name in (
        "case.json",
        "claim_graph.json",
        "evidence_ledger.json",
        "audit.jsonl",
        "bundle_manifest.json",
    ):
        assert (
            hashlib.sha256((first / name).read_bytes()).digest()
            == hashlib.sha256((second / name).read_bytes()).digest()
        )


def test_cli_rejects_malformed_case_and_audit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    case = tmp_path / "case.json"
    case.write_text('{"case_id":"case_bad","unknown":true}', encoding="utf-8")
    audit = tmp_path / "audit.jsonl"
    audit.write_text("not json\n", encoding="utf-8")
    assert main(["case", "validate", str(case), "--audit-file", str(audit)]) == 2
    assert "error:" in capsys.readouterr().err
    assert main(["audit", "verify", str(audit)]) == 2


def test_case_validation_requires_matching_complete_history(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    export_demo(run_demo("provisional"), first)
    export_demo(run_demo("fragile"), second)
    assert (
        main(
            [
                "case",
                "validate",
                str(first / "case.json"),
                "--audit-file",
                str(second / "audit.jsonl"),
            ]
        )
        == 2
    )
    assert "does not match" in capsys.readouterr().err


def test_default_demo_output_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["case", "run-demo", "--scenario", "fragile"]) == 0
    assert (tmp_path / "quantforge-demo-fragile" / "case.json").is_file()


def test_export_refuses_symlink_directory(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        export_demo(run_demo("provisional"), link)


def test_export_manifest_hashes_match_artifacts(tmp_path: Path) -> None:
    result = run_demo("fragile")
    output = tmp_path / "bundle"
    hashes = export_demo(result, output)
    assert hashes["case.json"] == canonical_sha256(result.case)
    assert hashes["claim_graph.json"] == canonical_sha256(result.claim_graph.snapshot())
    assert hashes["evidence_ledger.json"] == canonical_sha256(result.evidence_ledger.snapshot())
    assert hashes["audit.jsonl"] == canonical_sha256(result.audit_log.events)
    manifest = safe_load_json(output / "bundle_manifest.json")
    assert manifest["artifacts"] == {
        name: digest for name, digest in hashes.items() if name != "bundle_manifest.json"
    }
    assert hashes["bundle_manifest.json"] == canonical_sha256(manifest)
