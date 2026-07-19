from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from quantforge.adapters.governed_demo import GovernedTribunalMockProvider
from quantforge.cli import main as cli_module
from quantforge.cli.main import main
from quantforge.demo import run_governed_tribunal_demo, verify_governed_tribunal_demo
from quantforge.demo.tribunal import DEMONSTRATION_LABEL
from quantforge.domain.models import ChairExplanation, Verdict
from quantforge.engine.local_cpp import LocalCppV1Adapter
from quantforge.roles.contracts import ProviderResult, RoleAction
from tests.unit.test_engine_adapter import FixtureAdapter, _fake_environment, _sha256


class GovernedDemoFixtureAdapter(FixtureAdapter):
    """Use the production multi-artifact fact extraction against the bounded fake executable."""

    def __init__(self, **arguments: Any) -> None:
        super().__init__(**arguments)
        self.trusted_execution_count = 0

    def _extract_numeric_facts(self, output_root: Path) -> tuple[Any, ...]:
        return LocalCppV1Adapter._extract_numeric_facts(self, output_root)

    def execute_trusted_fixture(self, **arguments: Any) -> Any:
        self.trusted_execution_count += 1
        return super().execute_trusted_fixture(**arguments)


def _adapter(root: Path) -> GovernedDemoFixtureAdapter:
    repository, executable, work_root = _fake_environment(root)
    return GovernedDemoFixtureAdapter(
        repository=repository,
        executable=executable,
        expected_executable_sha256=_sha256(executable),
        work_root=work_root,
    )


def _run(root: Path, name: str = "artifacts") -> tuple[GovernedDemoFixtureAdapter, Any, Path]:
    adapter = _adapter(root / "fixture")
    output = root / name
    result = run_governed_tribunal_demo(adapter, output)
    return adapter, result, output


def test_repeated_runs_have_identical_governed_semantics_and_no_duplicate_transitions(
    tmp_path: Path,
) -> None:
    first_adapter, first, first_output = _run(tmp_path / "first")
    second_adapter, second, second_output = _run(tmp_path / "second")

    assert first.semantic_identities == second.semantic_identities
    assert first.case_revision_identity == second.case_revision_identity
    assert first.engine_bundle.semantic == second.engine_bundle.semantic
    assert first.verdict_eligibility == second.verdict_eligibility
    assert first.replay_status == second.replay_status
    assert first.replay_status.duplicate_transitions == 0
    assert first.replay_status.provider_invocations == 6
    assert first.replay_status.audit_events == first.case_revision == 12
    assert first_adapter.trusted_execution_count == second_adapter.trusted_execution_count == 1
    assert verify_governed_tribunal_demo(first_output)["valid"] is True
    assert verify_governed_tribunal_demo(second_output)["valid"] is True


def test_machine_output_binds_role_contracts_evidence_and_independent_reconstruction(
    tmp_path: Path,
) -> None:
    adapter, result, output = _run(tmp_path)
    evidence_ids = set(result.case.evidence_ids)

    assert result.demonstration_label == DEMONSTRATION_LABEL
    assert result.case.claim.submitted_by.startswith(DEMONSTRATION_LABEL)
    assert result.verdict_eligibility.verdict is Verdict.INCONCLUSIVE
    assert result.export_inventory.reconstruction_result["valid"] is True
    assert len(result.evidence) == 4
    assert sum(len(item.numeric_facts) for item in result.evidence) == 16
    assert result.trusted_execution_identity.adapter_contract_version == "cpp-v1-adapter/2.0"
    assert result.trusted_execution_identity.repository_snapshot_sha256
    assert result.trusted_execution_identity.validator_source_sha256
    assert result.trusted_execution_identity.run_fingerprint
    assert (
        result.semantic_identities.configuration_semantic_sha256
        == result.trusted_execution_identity.configuration_semantic_sha256
    )
    assert adapter.trusted_execution_count == 1
    for record in result.role_results:
        provenance = record.request_provenance
        accepted = record.accepted_result
        assert provenance.prompt_template_sha256
        assert provenance.structured_output_schema_sha256
        assert provenance.validation_policy_sha256
        assert provenance.provider_identity == "quantforge_offline_governed_demo_mock"
        assert accepted is not None
        assert accepted.semantic_provenance.provider_identity == provenance.provider_identity
        assert accepted.observational_provenance.transport_metadata["network_access"] is False

    statistical = result.case.statistical_review
    adversarial = result.case.adversarial_review
    assert statistical is not None and adversarial is not None
    for finding in (*statistical.findings, *adversarial.findings):
        assert {reference.evidence_id for reference in finding.evidence_references} == evidence_ids
    for challenge in adversarial.challenges:
        assert {
            reference.evidence_id for reference in challenge.evidence_references
        } == evidence_ids
    assert verify_governed_tribunal_demo(output)["case_package"]["complete"] is True
    with pytest.raises(ValueError, match="already exists"):
        run_governed_tribunal_demo(adapter, output)
    with pytest.raises(ValueError, match="regular non-symlink directory"):
        verify_governed_tribunal_demo(tmp_path / "missing-artifact-set")


def test_chair_wording_cannot_change_code_owned_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, baseline, _ = _run(tmp_path / "baseline")
    original = GovernedTribunalMockProvider.explain

    def alternate_explanation(
        self: GovernedTribunalMockProvider, case: Any, eligibility: Any
    ) -> ProviderResult[ChairExplanation]:
        initial = original(self, case, eligibility)
        output = initial.output.model_copy(
            update={
                "summary": (
                    "Alternative presentation wording leaves the previously computed eligibility "
                    "and decisive evidence unchanged"
                )
            }
        )
        return self._result(
            RoleAction.EXPLAIN_VERDICT,
            output,
            output.created_at,
            ProviderResult[ChairExplanation],
        )

    monkeypatch.setattr(GovernedTribunalMockProvider, "explain", alternate_explanation)
    _, alternate, _ = _run(tmp_path / "alternate")

    assert alternate.verdict_eligibility == baseline.verdict_eligibility
    assert alternate.case.verdict_eligibility == baseline.case.verdict_eligibility
    assert alternate.case.chair_explanation != baseline.case.chair_explanation


@pytest.mark.parametrize("target", ["tribunal-report.md", "demo-manifest.json"])
@pytest.mark.malicious
def test_report_and_outer_manifest_tampering_is_detected(tmp_path: Path, target: str) -> None:
    _, _, original = _run(tmp_path / "run")
    tampered = tmp_path / "tampered"
    shutil.copytree(original, tampered)
    path = tampered / target
    if target.endswith(".json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        document["case_id"] = "case_substituted_demo"
        path.write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")
    else:
        path.write_text(path.read_text(encoding="utf-8") + "\nsubstituted\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"identity|hash mismatch"):
        verify_governed_tribunal_demo(tampered)


@pytest.mark.malicious
def test_stale_substituted_or_extra_case_package_artifacts_are_rejected(tmp_path: Path) -> None:
    _, _, original = _run(tmp_path / "run")
    substituted = tmp_path / "substituted"
    shutil.copytree(original, substituted)
    case_file = substituted / "case-package/case.json"
    case_file.write_bytes((substituted / "case-spec.json").read_bytes())
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_governed_tribunal_demo(substituted)

    extra = tmp_path / "extra"
    shutil.copytree(original, extra)
    (extra / "case-package/stale-case.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing, extra, or substituted"):
        verify_governed_tribunal_demo(extra)


def test_mock_provider_has_no_engine_evidence_or_workflow_mutation_authority() -> None:
    provider = GovernedTribunalMockProvider()
    forbidden = (
        "execute_approved_fixture",
        "execute_trusted_fixture",
        "admit_engine_evidence",
        "append_event",
        "advance",
    )
    assert all(not hasattr(provider, name) for name in forbidden)
    assert provider.provider_identity == "quantforge_offline_governed_demo_mock"


def test_governed_demo_cli_runs_and_independently_verifies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    adapter = _adapter(tmp_path / "fixture")
    output = tmp_path / "cli-artifacts"
    monkeypatch.setattr(cli_module, "_adapter", lambda _arguments: adapter)
    engine_arguments = [
        "--repository",
        str(adapter._repository),
        "--executable",
        str(adapter._executable),
        "--expected-executable-sha256",
        _sha256(adapter._executable),
        "--work-root",
        str(adapter._work_root),
    ]
    assert main(["demo", "run", *engine_arguments, "--output-dir", str(output)]) == 0
    summary = capsys.readouterr().out
    assert DEMONSTRATION_LABEL in summary
    assert "Deterministic verdict: INCONCLUSIVE" in summary
    assert f"quantforge demo verify {output}" in summary

    assert main(["demo", "verify", str(output)]) == 0
    verification = json.loads(capsys.readouterr().out)
    assert verification["valid"] is True
    assert verification["verdict"] == "INCONCLUSIVE"
