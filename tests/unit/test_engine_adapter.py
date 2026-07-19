from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from quantforge.audit import AuditLog
from quantforge.cli import main as cli_module
from quantforge.cli.main import main
from quantforge.domain.models import RoleName, WorkflowState
from quantforge.engine.base import EngineAdapter
from quantforge.engine.local_cpp import (
    APPROVED_CONFIG,
    APPROVED_INPUTS,
    APPROVED_VALIDATOR,
    LocalCppV1Adapter,
    _ProcessResult,
    _read_engine_json,
    _RepositorySnapshot,
    _validate_output_artifact,
)
from quantforge.engine.trust import TrustedExecutionReceipt
from quantforge.evidence.bundle import (
    EngineIdentity,
    EvidenceAdmissionContext,
    HmacSha256TestSigner,
    ValidatorResult,
    amendment_chain_hash,
    evidence_from_bundle,
    verify_evidence_bundle,
)
from quantforge.evidence.ledger import EvidenceLedger
from quantforge.serialization.canonical import canonical_sha256
from quantforge.storage import (
    SQLiteCaseStore,
    admit_engine_evidence,
    execute_and_admit_engine_evidence,
    export_durable_case,
    persist_audited_case,
    verify_case_package,
)
from quantforge.workflow.demo import run_demo
from quantforge.workflow.machine import StateMachine


class ReleaseFixtureAdapter(LocalCppV1Adapter):
    @staticmethod
    def _run_bounded(
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: dict[str, str],
        timeout_seconds: int,
        log_directory: Path | None,
        log_name: str,
        require_success: bool = True,
    ) -> _ProcessResult:
        if argv and Path(argv[0]).name == "quant_cli_fixture.py":
            argv = (sys.executable, *argv)
        return LocalCppV1Adapter._run_bounded(
            argv,
            cwd=cwd,
            environment=environment,
            timeout_seconds=timeout_seconds,
            log_directory=log_directory,
            log_name=log_name,
            require_success=require_success,
        )


class FixtureAdapter(ReleaseFixtureAdapter):
    def verify_release_identity(self) -> EngineIdentity:
        self._validate_executable()
        return EngineIdentity(executable_sha256=_sha256(self._executable))

    def _repository_snapshot(self) -> _RepositorySnapshot:
        inventory: list[tuple[str, str, int]] = []
        for candidate in sorted(self._repository.rglob("*")):
            relative = candidate.relative_to(self._repository)
            if relative.parts[0] == ".git":
                continue
            if candidate.is_symlink():
                raise ValueError("protected repository inventory contains a forbidden symlink")
            if candidate.is_file():
                inventory.append(
                    (relative.as_posix(), _sha256(candidate), candidate.stat().st_size)
                )
            elif not candidate.is_dir():
                raise ValueError("protected repository inventory contains a forbidden file type")
        digest = canonical_sha256(inventory)
        return _RepositorySnapshot(
            repository_root=str(self._repository),
            git_common_directory=str(self._repository / ".git"),
            remote="fixture",
            head="fixture",
            branch="fixture",
            tag_object="fixture",
            tag_target="fixture",
            tag_type="fixture",
            refs_sha256=digest,
            status_sha256=digest,
            tracked_diff_sha256=digest,
            staged_diff_sha256=digest,
            tracked_inventory_sha256=digest,
            untracked_inventory_sha256=digest,
            ignored_inventory_sha256=digest,
        )

    def _extract_numeric_facts(self, output_root: Path) -> tuple[Any, ...]:
        return (self._extract_numeric_fact(output_root),)


class HostileFixtureAdapter(FixtureAdapter):
    def __init__(
        self,
        *,
        repository: Path,
        executable: Path,
        expected_executable_sha256: str,
        work_root: Path,
        hostile_action: str,
    ) -> None:
        super().__init__(
            repository=repository,
            executable=executable,
            expected_executable_sha256=expected_executable_sha256,
            work_root=work_root,
        )
        self._hostile_action = hostile_action

    def _run_engine(
        self,
        arguments: tuple[str, ...],
        run_root: Path,
        environment: dict[str, str],
        logs: Path,
        log_name: str,
    ) -> _ProcessResult:
        hostile_environment = {
            **environment,
            "QF_HOSTILE": self._hostile_action,
            "QF_REPOSITORY": str(self._repository),
        }
        return super()._run_engine(
            arguments,
            run_root,
            hostile_environment,
            logs,
            log_name,
        )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_engine_adapter_abstract_defaults_fail_closed() -> None:
    receiver = cast(EngineAdapter, None)
    getter = cast(Any, EngineAdapter.allowed_commands).fget
    assert getter is not None
    calls = (
        lambda: getter(receiver),
        lambda: EngineAdapter.verify_release_identity(receiver),
        lambda: EngineAdapter.approved_fixture_identity(receiver),
        lambda: EngineAdapter.execute_approved_fixture(receiver),
        lambda: EngineAdapter.execute_trusted_fixture(
            receiver,
            case_id="case",
            workflow_revision=1,
            constitution_id="constitution",
            constitution_hash="1" * 64,
            amendment_chain_hash="2" * 64,
        ),
    )
    for call in calls:
        with pytest.raises(NotImplementedError):
            call()


def _fake_environment(tmp_path: Path) -> tuple[Path, Path, Path]:
    repository = tmp_path / "engine"
    repository.mkdir(parents=True)
    (repository / ".git").mkdir()
    for relative in (APPROVED_CONFIG, *APPROVED_INPUTS, APPROVED_VALIDATOR):
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative == APPROVED_CONFIG:
            path.write_text('{"approved":true}\n', encoding="utf-8")
        elif relative == APPROVED_VALIDATOR:
            path.write_text(
                """
from pathlib import Path
summary = Path("results/fixture/portfolio_performance_summary.csv")
if not summary.is_file():
    raise SystemExit(2)
print("validation passed")
""".lstrip(),
                encoding="utf-8",
            )
        elif path.suffix == ".json":
            path.write_text('{"fixture":"synthetic"}\n', encoding="utf-8")
        else:
            path.write_text("Date,Close\n2026-01-01,1\n", encoding="utf-8")
    executable = tmp_path / "quant_cli_fixture.py"
    executable.write_text(
        f"""#!{sys.executable}
import json
import os
import pathlib
import sys
import time

command = sys.argv[1] if len(sys.argv) > 1 else ""
if command == "version":
    print("cpp-event-driven-backtester 1.0.0")
    print("stochastic_methodology_version=2")
    print("rng_mapping=portable_bounded_v1")
elif command == "sleep":
    time.sleep(5)
elif command == "flood":
    sys.stdout.write("x" * 1100000)
elif command == "fail":
    print("fixture failure", file=sys.stderr)
    raise SystemExit(7)
elif command == "run" and "--dry-run" not in sys.argv:
    if os.environ.get("QF_POISON"):
        raise SystemExit(8)
    output = pathlib.Path("results/fixture")
    output.mkdir(parents=True)
    (output / "portfolio_performance_summary.csv").write_text(
        "schema_version,total_return,spy_benchmark_return,excess_return,annualized_return,"
        "sharpe,max_drawdown,turnover,total_transaction_costs\\n"
        "3,0.125,0.05,0.075,0.02,0.4,-0.2,1.5,125\\n",
        encoding="utf-8",
    )
    statistics = output / "statistics"
    statistics.mkdir()
    (statistics / "multiple_testing_summary.csv").write_text(
        "schema_version,p_value\\n3,0.30\\n", encoding="utf-8"
    )
    (statistics / "portfolio_policy_robustness.csv").write_text(
        "schema_version,probability_loss,probability_positive_active,return_lower,"
        "return_upper,sharpe_lower,sharpe_upper\\n"
        "3,0.25,0.65,-0.8,2.0,-1.0,2.4\\n",
        encoding="utf-8",
    )
    attribution = output / "attribution"
    attribution.mkdir()
    (attribution / "portfolio_attribution_summary.csv").write_text(
        "schema_version,component,percentage_of_net_profit\\n"
        "3,SYN_CRYPTO,0.50\\n3,PORTFOLIO_RETURN,1.0\\n",
        encoding="utf-8",
    )
    (output / "run_metadata.json").write_text(
        json.dumps({{"result_schema_version": 2, "run_timestamp_utc": "now"}}) + "\\n",
        encoding="utf-8",
    )
    print("experiment complete")
else:
    hostile = os.environ.get("QF_HOSTILE")
    if hostile and command == "validate-config":
        targets = {{
            "configuration": pathlib.Path("configs/portfolio_equal_weight.json"),
            "input_csv": pathlib.Path("data/synthetic/SYN_BENCH.csv"),
            "input_json": pathlib.Path("data/synthetic/metadata.json"),
            "validator": pathlib.Path("scripts/validate_results.py"),
        }}
        if hostile in targets:
            target = targets[hostile]
            target.chmod(0o600)
            target.write_text(target.read_text(encoding="utf-8") + " ", encoding="utf-8")
        elif hostile == "executable":
            own = pathlib.Path(__file__)
            own.write_text(own.read_text(encoding="utf-8") + "\\n# changed\\n", encoding="utf-8")
        elif hostile == "repository_file":
            repository_file = (
                pathlib.Path(os.environ["QF_REPOSITORY"])
                / "data/synthetic/SYN_EQ_A.csv"
            )
            repository_file.write_text(
                repository_file.read_text(encoding="utf-8") + "2026-01-02,2\\n",
                encoding="utf-8",
            )
        elif hostile == "symlink_target":
            target = pathlib.Path("hostile-target.json")
            target.write_text('{{"hostile":true}}\\n', encoding="utf-8")
            link = pathlib.Path("configs/portfolio_equal_weight.json")
            link.parent.chmod(0o700)
            link.unlink()
            link.symlink_to(target.resolve())
    print(json.dumps({{"command": command, "valid": True}}))
""",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    work_root = tmp_path / "work"
    work_root.mkdir()
    return repository, executable, work_root


def _adapter(tmp_path: Path) -> FixtureAdapter:
    repository, executable, work_root = _fake_environment(tmp_path)
    return FixtureAdapter(
        repository=repository,
        executable=executable,
        expected_executable_sha256=_sha256(executable),
        work_root=work_root,
    )


def _hostile_adapter(tmp_path: Path, hostile_action: str) -> HostileFixtureAdapter:
    repository, executable, work_root = _fake_environment(tmp_path)
    return HostileFixtureAdapter(
        repository=repository,
        executable=executable,
        expected_executable_sha256=_sha256(executable),
        work_root=work_root,
        hostile_action=hostile_action,
    )


def test_fixture_execution_uses_only_allowlisted_argv_and_isolated_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _adapter(tmp_path)
    monkeypatch.setenv("QF_POISON", "must-not-cross-boundary")
    run = adapter.execute_approved_fixture()
    assert run.engine.executable_sha256 == _sha256(adapter._executable)
    assert run.configuration_sha256 == _sha256(run.run_root / APPROVED_CONFIG)
    assert len(run.input_semantics) == len(APPROVED_INPUTS)
    assert [item.path for item in run.output_semantics] == [
        "fixture/attribution/portfolio_attribution_summary.csv",
        "fixture/portfolio_performance_summary.csv",
        "fixture/run_metadata.json",
        "fixture/statistics/multiple_testing_summary.csv",
        "fixture/statistics/portfolio_policy_robustness.csv",
    ]
    assert len(run.numeric_facts) == 1
    assert run.numeric_facts[0].value.is_finite()
    exponent = run.numeric_facts[0].value.as_tuple().exponent
    assert isinstance(exponent, int) and exponent < 0
    assert run.validators[0].status == "passed"
    assert all(command[0] in {"python", "quant_cli"} for command in adapter.allowed_commands)
    assert not (adapter._repository / "results").exists()


@pytest.mark.parametrize(
    "hostile_action",
    [
        "configuration",
        "input_csv",
        "input_json",
        "validator",
        "executable",
        "repository_file",
        "symlink_target",
    ],
)
@pytest.mark.malicious
def test_post_child_identity_rejects_hostile_mutation(tmp_path: Path, hostile_action: str) -> None:
    adapter = _hostile_adapter(tmp_path / hostile_action, hostile_action)
    with pytest.raises(ValueError, match=r"changed|identity|inventory|symlink|boundary"):
        adapter.execute_approved_fixture()


@pytest.mark.malicious
def test_trusted_receipt_is_code_owned_case_bound_and_one_shot(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    execution = adapter.execute_trusted_fixture(
        case_id="case_receipt",
        workflow_revision=5,
        constitution_id="constitution_receipt",
        constitution_hash="1" * 64,
        amendment_chain_hash="2" * 64,
    )
    with pytest.raises(TypeError, match="approved adapter"):
        TrustedExecutionReceipt(execution.receipt.record)
    run = execution.run
    admitted_at = run.execution_completed_at + timedelta(seconds=1)
    foreign = run.evidence_bundle(
        bundle_id="bundle_foreign",
        case_id="case_foreign",
        workflow_revision=5,
        constitution_id="constitution_receipt",
        constitution_hash="1" * 64,
        amendment_chain_hash="2" * 64,
        previous_bundle_hash="0" * 64,
        admitted_at=admitted_at,
    )
    record = execution.receipt.record
    with pytest.raises(ValueError, match="case revision"):
        execution.receipt._consume(
            run,
            foreign,
            configuration_semantic_sha256=record.configuration_semantic_sha256,
            repository_snapshot_sha256=record.repository_snapshot_sha256,
            validator_source_sha256=record.validator_source_sha256,
        )
    bundle = run.evidence_bundle(
        bundle_id="bundle_receipt",
        case_id="case_receipt",
        workflow_revision=5,
        constitution_id="constitution_receipt",
        constitution_hash="1" * 64,
        amendment_chain_hash="2" * 64,
        previous_bundle_hash="0" * 64,
        admitted_at=admitted_at,
    )
    execution.receipt._consume(
        run,
        bundle,
        configuration_semantic_sha256=record.configuration_semantic_sha256,
        repository_snapshot_sha256=record.repository_snapshot_sha256,
        validator_source_sha256=record.validator_source_sha256,
    )
    with pytest.raises(ValueError, match="already been consumed"):
        execution.receipt._consume(
            run,
            bundle,
            configuration_semantic_sha256=record.configuration_semantic_sha256,
            repository_snapshot_sha256=record.repository_snapshot_sha256,
            validator_source_sha256=record.validator_source_sha256,
        )


def test_approved_fixture_identity_is_independent_of_staging(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    identity = adapter.approved_fixture_identity()
    assert identity.engine.executable_sha256 == _sha256(adapter._executable)
    assert identity.configuration_sha256 == _sha256(adapter._repository / APPROVED_CONFIG)
    assert [item.path for item in identity.input_semantics] == sorted(
        path.as_posix() for path in APPROVED_INPUTS
    )


@pytest.mark.skipif(sys.platform == "win32", reason="production adapter supports Linux/macOS")
def test_repository_snapshot_hashes_all_git_boundary_inventories(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()

    def git(*arguments: str) -> None:
        subprocess.run(  # noqa: S603 - fixed git binary and test-owned arguments
            ("/usr/bin/git", *arguments),
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )

    git("init")
    git("config", "user.name", "QuantForge Test")
    git("config", "user.email", "quantforge@example.invalid")
    (repository / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (repository / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    git("add", ".gitignore", "tracked.txt")
    git("commit", "-m", "fixture")
    git("tag", "-a", "v1.0.0", "-m", "fixture tag")
    git("remote", "add", "origin", "https://github.com/example/fixture.git")
    (repository / "untracked.txt").write_text("untracked\n", encoding="utf-8")
    (repository / "ignored.txt").write_text("ignored\n", encoding="utf-8")
    executable = tmp_path / "unused-executable"
    executable.write_bytes(b"fixture")
    adapter = ReleaseFixtureAdapter(
        repository=repository,
        executable=executable,
        expected_executable_sha256=_sha256(executable),
        work_root=tmp_path,
    )
    before = adapter._repository_snapshot()
    (repository / "tracked.txt").write_text("mutated\n", encoding="utf-8")
    after = adapter._repository_snapshot()
    assert before.repository_root == str(repository)
    assert before.tag_type == "tag"
    assert before.tracked_inventory_sha256 != after.tracked_inventory_sha256
    assert before.status_sha256 != after.status_sha256


@pytest.mark.parametrize(
    "approved_remote",
    [
        "https://github.com/MrithunjoyB/cpp-event-driven-backtester",
        "https://github.com/MrithunjoyB/cpp-event-driven-backtester.git",
    ],
)
def test_real_release_identity_checks_exact_remote_tag_and_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, approved_remote: str
) -> None:
    repository, executable, work_root = _fake_environment(tmp_path)
    adapter = ReleaseFixtureAdapter(
        repository=repository,
        executable=executable,
        expected_executable_sha256=_sha256(executable),
        work_root=work_root,
    )

    def git_result(*arguments: str, **_kwargs: object) -> _ProcessResult:
        values = {
            ("config", "--get", "remote.origin.url"): (f"{approved_remote}\n".encode()),
            ("status", "--porcelain=v1", "--untracked-files=no"): b"",
            ("rev-parse", "refs/tags/v1.0.0"): (b"20ac53c5e4b61ae7b431d5bb263f246e35f8d2a2\n"),
            ("rev-parse", "refs/tags/v1.0.0^{}"): (b"2f86b71dbc9f29dbda861942d8afbb10c04b6625\n"),
            ("cat-file", "-t", "refs/tags/v1.0.0"): b"tag\n",
        }
        output = values.get(arguments, b"")
        return _ProcessResult(("git", *arguments), 0, output, b"")

    monkeypatch.setattr(adapter, "_git", git_result)
    identity = adapter.verify_release_identity()
    assert identity.release == "v1.0.0"
    assert identity.executable_sha256 == _sha256(executable)


@pytest.mark.parametrize(
    ("arguments", "stdout", "message"),
    [
        (
            ("config", "--get", "remote.origin.url"),
            b"https://github.com/attacker/repository.git\n",
            "remote",
        ),
        (("status",), b" M configs/portfolio_equal_weight.json\n", "not clean"),
        (("rev-parse",), b"f" * 40 + b"\n", "tag identity"),
    ],
)
def test_release_identity_substitution_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arguments: tuple[str, ...],
    stdout: bytes,
    message: str,
) -> None:
    repository, executable, work_root = _fake_environment(tmp_path)
    adapter = LocalCppV1Adapter(
        repository=repository,
        executable=executable,
        expected_executable_sha256=_sha256(executable),
        work_root=work_root,
    )

    def git_result(*actual: str, **_kwargs: object) -> _ProcessResult:
        defaults = {
            ("config", "--get", "remote.origin.url"): (
                b"https://github.com/MrithunjoyB/cpp-event-driven-backtester.git\n"
            ),
            ("status", "--porcelain=v1", "--untracked-files=no"): b"",
            ("rev-parse", "refs/tags/v1.0.0"): (b"20ac53c5e4b61ae7b431d5bb263f246e35f8d2a2\n"),
            ("rev-parse", "refs/tags/v1.0.0^{}"): (b"2f86b71dbc9f29dbda861942d8afbb10c04b6625\n"),
            ("cat-file", "-t", "refs/tags/v1.0.0"): b"tag\n",
        }
        selected = defaults.get(actual, b"")
        if (
            (arguments == ("status",) and actual[0] == "status")
            or (arguments == ("rev-parse",) and actual == ("rev-parse", "refs/tags/v1.0.0"))
            or actual == arguments
        ):
            selected = stdout
        return _ProcessResult(("git", *actual), 0, selected, b"")

    monkeypatch.setattr(adapter, "_git", git_result)
    with pytest.raises(ValueError, match=message):
        adapter.verify_release_identity()


def test_executable_substitution_and_symlink_paths_are_rejected(tmp_path: Path) -> None:
    repository, executable, work_root = _fake_environment(tmp_path / "digest")
    changed = FixtureAdapter(
        repository=repository,
        executable=executable,
        expected_executable_sha256="f" * 64,
        work_root=work_root,
    )
    with pytest.raises(ValueError, match="SHA-256"):
        changed.verify_release_identity()

    repository, executable, work_root = _fake_environment(tmp_path / "link")
    link = tmp_path / "linked-executable"
    link.symlink_to(executable)
    linked = FixtureAdapter(
        repository=repository,
        executable=link,
        expected_executable_sha256=_sha256(executable),
        work_root=work_root,
    )
    with pytest.raises(ValueError, match="symlink"):
        linked.verify_release_identity()


def test_command_injection_is_rejected_before_process_creation(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    run_root = tmp_path / "run"
    run_root.mkdir()
    logs = run_root / ".adapter-logs"
    logs.mkdir()
    with pytest.raises(ValueError, match="allow-list"):
        adapter._run_engine(
            ("run;touch", "attacker"),
            run_root,
            adapter._minimal_environment(run_root),
            logs,
            "injection",
        )
    assert not (tmp_path / "attacker").exists()


def test_process_timeout_output_flood_and_nonzero_status_are_bounded(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    environment = adapter._minimal_environment(tmp_path / "runtime")
    with pytest.raises(ValueError, match="timed out"):
        adapter._run_bounded(
            (str(adapter._executable), "sleep"),
            cwd=tmp_path,
            environment=environment,
            timeout_seconds=1,
            log_directory=tmp_path / "sleep-logs",
            log_name="sleep",
        )
    with pytest.raises(ValueError, match="output limits"):
        adapter._run_bounded(
            (str(adapter._executable), "flood"),
            cwd=tmp_path,
            environment=environment,
            timeout_seconds=5,
            log_directory=tmp_path / "flood-logs",
            log_name="flood",
        )
    with pytest.raises(ValueError, match="failed with 7"):
        adapter._run_bounded(
            (str(adapter._executable), "fail"),
            cwd=tmp_path,
            environment=environment,
            timeout_seconds=5,
            log_directory=tmp_path / "fail-logs",
            log_name="fail",
        )


def test_staging_and_output_inventory_reject_symlinks_and_unknown_types(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path / "input")
    input_path = adapter._repository / APPROVED_INPUTS[0]
    target = input_path.with_suffix(".target")
    input_path.replace(target)
    input_path.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        adapter.execute_approved_fixture()

    adapter = _adapter(tmp_path / "output")
    root = tmp_path / "output-root"
    root.mkdir()
    (root / "artifact.bin").write_bytes(b"unknown")
    with pytest.raises(ValueError, match="undeclared artifact type"):
        adapter._inventory_outputs(root)


def test_malformed_and_nonfinite_csv_outputs_are_rejected(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    malformed = tmp_path / "malformed"
    malformed.mkdir()
    (malformed / "portfolio_performance_summary.csv").write_text(
        'schema_version,total_return\n3,"unterminated\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="malformed"):
        adapter._inventory_outputs(malformed)

    nonfinite = tmp_path / "nonfinite"
    nonfinite.mkdir()
    (nonfinite / "portfolio_performance_summary.csv").write_text(
        "schema_version,total_return\n3,Infinity\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="non-finite"):
        adapter._inventory_outputs(nonfinite)


def test_adapter_rejects_invalid_roots_boundaries_and_process_vectors(tmp_path: Path) -> None:
    repository, executable, work_root = _fake_environment(tmp_path / "fixture")
    adapter = FixtureAdapter(
        repository=repository,
        executable=executable,
        expected_executable_sha256=_sha256(executable),
        work_root=work_root,
    )
    empty = tmp_path / "empty-output"
    empty.mkdir()
    with pytest.raises(ValueError, match="empty"):
        adapter._inventory_outputs(empty)

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "forbidden.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="boundary"):
        adapter._verify_run_boundary(outside)
    (outside / "forbidden.txt").unlink()
    (outside / "link").symlink_to(executable)
    with pytest.raises(ValueError, match="symlink"):
        adapter._verify_run_boundary(outside)

    environment = adapter._minimal_environment(tmp_path / "env")
    with pytest.raises(ValueError, match="argument vector"):
        adapter._run_bounded(
            (),
            cwd=tmp_path,
            environment=environment,
            timeout_seconds=1,
            log_directory=tmp_path / "logs-empty",
            log_name="empty",
        )
    with pytest.raises(ValueError, match="argument vector"):
        adapter._run_bounded(
            (str(executable), "bad\0argument"),
            cwd=tmp_path,
            environment=environment,
            timeout_seconds=1,
            log_directory=tmp_path / "logs-null",
            log_name="null",
        )

    missing_repository = FixtureAdapter(
        repository=tmp_path / "missing",
        executable=executable,
        expected_executable_sha256=_sha256(executable),
        work_root=work_root,
    )
    with pytest.raises(ValueError, match="repository"):
        missing_repository._validate_repository_root()
    not_git = tmp_path / "not-git"
    not_git.mkdir()
    missing_repository = FixtureAdapter(
        repository=not_git,
        executable=executable,
        expected_executable_sha256=_sha256(executable),
        work_root=work_root,
    )
    with pytest.raises(ValueError, match="Git repository"):
        missing_repository._validate_repository_root()
    bad_work = FixtureAdapter(
        repository=repository,
        executable=executable,
        expected_executable_sha256=_sha256(executable),
        work_root=tmp_path / "missing-work",
    )
    with pytest.raises(ValueError, match="work root"):
        bad_work._validate_work_root()
    executable.chmod(0o600)
    if os.name == "posix":
        with pytest.raises(ValueError, match="not executable"):
            adapter._validate_executable()
    else:
        adapter._validate_executable()


def test_adapter_validates_json_csv_schemas_and_numeric_fact_shape(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path / "adapter")
    json_without_schema = tmp_path / "without-schema.json"
    json_without_schema.write_text('{"valid":true}\n', encoding="utf-8")
    assert _validate_output_artifact(json_without_schema) == "validated-v1"
    json_unknown = tmp_path / "unknown.json"
    json_unknown.write_text('{"result_schema_version":4}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="unknown result schema"):
        _validate_output_artifact(json_unknown)
    json_duplicate = tmp_path / "duplicate.json"
    json_duplicate.write_text('{"value":1,"value":2}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON"):
        _read_engine_json(json_duplicate)
    json_malformed = tmp_path / "malformed.json"
    json_malformed.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="malformed"):
        _read_engine_json(json_malformed)
    json_deep = tmp_path / "deep.json"
    json_deep.write_text("[" * 66 + "0" + "]" * 66, encoding="utf-8")
    with pytest.raises(ValueError, match="nesting"):
        _read_engine_json(json_deep)

    no_schema = tmp_path / "no-schema.csv"
    no_schema.write_text("value\n1\n", encoding="utf-8")
    assert _validate_output_artifact(no_schema) == "validated-v1"
    mixed = tmp_path / "mixed.csv"
    mixed.write_text("schema_version,value\n2,1\n3,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mixed or unknown"):
        _validate_output_artifact(mixed)
    duplicate_header = tmp_path / "headers.csv"
    duplicate_header.write_text("value,value\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate headers"):
        _validate_output_artifact(duplicate_header)

    output = tmp_path / "numeric"
    output.mkdir()
    with pytest.raises(ValueError, match="one portfolio summary"):
        adapter._extract_numeric_fact(output)
    summary = output / "portfolio_performance_summary.csv"
    summary.write_text("schema_version,value\n3,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="numeric fact"):
        adapter._extract_numeric_fact(output)
    summary.write_text("schema_version,total_return\n3,not-a-decimal\n", encoding="utf-8")
    with pytest.raises(ValueError, match="malformed"):
        adapter._extract_numeric_fact(output)


def test_verified_bundle_and_experiment_event_commit_atomically(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path / "adapter")
    complete = run_demo("provisional")
    prefix = AuditLog(complete.audit_log.events[:5])
    case = prefix.replay_case(require_complete=False)
    assert case.constitution is not None
    store = SQLiteCaseStore(tmp_path / "cases.sqlite3")
    store.initialize()
    persist_audited_case(store, prefix)
    signer = HmacSha256TestSigner(
        signer_id="signer_fixture", secret=b"0123456789abcdef0123456789abcdef"
    )
    admitted = execute_and_admit_engine_evidence(
        store,
        adapter,
        case_id=case.case_id,
        evidence_id="evidence_engine_fixture",
        signer=signer,
    )
    assert admitted.durable_case.revision == 6
    assert admitted.durable_case.case.state.value == "EXPERIMENT_EXECUTED"
    assert store.inspect().bundle_count == 1
    assert store.list_evidence_bundles(case.case_id) == (admitted.bundle,)
    store.verify()
    package = tmp_path / "engine-package"
    export_durable_case(store, case.case_id, package)
    assert verify_case_package(package)["valid"] is True

    with pytest.raises(ValueError, match="locked, not-yet-executed"):
        execute_and_admit_engine_evidence(
            store,
            adapter,
            case_id=case.case_id,
            evidence_id="evidence_duplicate",
            signer=signer,
        )


@pytest.mark.malicious
def test_forged_structurally_valid_bundle_cannot_claim_execution_authenticity(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path / "adapter")
    run = adapter.execute_approved_fixture()
    summary = run.output_root / "fixture/portfolio_performance_summary.csv"
    summary.write_text("schema_version,total_return\n3,9.999\n", encoding="utf-8")
    output_semantics, output_observations = adapter._inventory_outputs(run.output_root)
    forged_run = replace(
        run,
        output_semantics=output_semantics,
        output_observations=output_observations,
        validators=(
            ValidatorResult(
                name="validate_results",
                status="passed",
                output_sha256="f" * 64,
            ),
        ),
        numeric_facts=(adapter._extract_numeric_fact(run.output_root),),
    )
    complete = run_demo("provisional")
    prefix = AuditLog(complete.audit_log.events[:5])
    case = prefix.replay_case(require_complete=False)
    assert case.constitution is not None and case.proposal is not None
    store = SQLiteCaseStore(tmp_path / "forged.sqlite3")
    store.initialize()
    persist_audited_case(store, prefix)
    admitted_at = forged_run.execution_completed_at + timedelta(seconds=1)
    bundle = forged_run.evidence_bundle(
        bundle_id="bundle_forged_numeric_result",
        case_id=case.case_id,
        workflow_revision=5,
        constitution_id=case.constitution.constitution_id,
        constitution_hash=case.constitution.constitution_hash,
        amendment_chain_hash=amendment_chain_hash(case.amendments),
        previous_bundle_hash="0" * 64,
        admitted_at=admitted_at,
    )
    approved = adapter.approved_fixture_identity()
    context = EvidenceAdmissionContext(
        case_id=case.case_id,
        workflow_revision=5,
        constitution_id=case.constitution.constitution_id,
        constitution_hash=case.constitution.constitution_hash,
        amendment_chain_hash=amendment_chain_hash(case.amendments),
        engine=approved.engine,
        configuration_sha256=approved.configuration_sha256,
        input_artifacts=approved.input_semantics,
        input_artifact_observations=approved.input_observations,
        now=admitted_at,
    )
    verify_evidence_bundle(bundle, context, forged_run.output_root)
    with pytest.raises(ValueError, match="standalone"):
        admit_engine_evidence(
            store,
            bundle,
            context,
            forged_run.output_root,
            evidence_id="evidence_forged_numeric_result",
        )
    evidence = evidence_from_bundle(
        bundle,
        evidence_id="evidence_forged_numeric_result",
        claim_id=case.claim.claim_id,
        experiment_id=case.proposal.experiment_id,
    )
    ledger = EvidenceLedger(
        case_id=case.case_id,
        experiment_id=case.proposal.experiment_id,
        constitution_hash=case.constitution.constitution_hash,
        claim_ids={case.claim.claim_id},
    )
    ledger.append(evidence)
    machine = StateMachine(case, prefix)
    machine.advance(
        WorkflowState.EXPERIMENT_EXECUTED,
        actor=RoleName.SYSTEM,
        action="admit_engine_evidence",
        timestamp=admitted_at,
        payload=ledger.snapshot(),
        updates={"evidence_ids": (evidence.evidence_id,)},
    )
    with pytest.raises(ValueError, match="trusted execution receipt"):
        store.admit_evidence_bundle(
            bundle,
            machine.audit_log.events[-1],
            expected_revision=5,
        )
    assert store.inspect().bundle_count == 0
    assert store.inspect().event_count == 5


@pytest.mark.parametrize(
    "mutation",
    [
        "null_bundle_id",
        "substitute_bundle_id",
        "delete_bundle",
        "delete_artifact",
        "substitute_artifact",
    ],
)
@pytest.mark.malicious
def test_engine_bundle_materialization_mutations_fail_reconstruction(
    tmp_path: Path, mutation: str
) -> None:
    adapter = _adapter(tmp_path / "adapter")
    result = run_demo("provisional")
    prefix = AuditLog(result.audit_log.events[:5])
    store = SQLiteCaseStore(tmp_path / f"{mutation}.sqlite3")
    store.initialize()
    persist_audited_case(store, prefix)
    admitted = execute_and_admit_engine_evidence(
        store,
        adapter,
        case_id="case_provisional",
        evidence_id="evidence_engine_mutation",
    )
    bundle_id = admitted.bundle.semantic.bundle_id
    connection = sqlite3.connect(store.path)
    try:
        if mutation == "null_bundle_id":
            connection.execute(
                "UPDATE evidence_records SET bundle_id = NULL WHERE case_id = ?",
                ("case_provisional",),
            )
        elif mutation == "substitute_bundle_id":
            substitute = "bundle_substituted"
            connection.execute(
                "UPDATE evidence_records SET bundle_id = ? WHERE case_id = ?",
                (substitute, "case_provisional"),
            )
            connection.execute(
                "UPDATE evidence_bundles SET bundle_id = ? WHERE bundle_id = ?",
                (substitute, bundle_id),
            )
            connection.execute(
                "UPDATE bundle_artifacts SET bundle_id = ? WHERE bundle_id = ?",
                (substitute, bundle_id),
            )
        elif mutation == "delete_bundle":
            connection.execute("DELETE FROM evidence_bundles WHERE bundle_id = ?", (bundle_id,))
        elif mutation == "delete_artifact":
            connection.execute(
                """
                DELETE FROM bundle_artifacts WHERE rowid = (
                    SELECT rowid FROM bundle_artifacts WHERE bundle_id = ? LIMIT 1
                )
                """,
                (bundle_id,),
            )
        else:
            connection.execute(
                """
                UPDATE bundle_artifacts SET byte_sha256 = ? WHERE rowid = (
                    SELECT rowid FROM bundle_artifacts WHERE bundle_id = ? LIMIT 1
                )
                """,
                ("a" * 64, bundle_id),
            )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(ValueError):
        store.reconstruct("case_provisional")


def test_failed_bundle_admission_rolls_back_bundle_and_event(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path / "adapter")
    run = adapter.execute_approved_fixture()
    complete = run_demo("fragile")
    prefix = AuditLog(complete.audit_log.events[:5])
    case = prefix.replay_case(require_complete=False)
    assert case.constitution is not None
    store = SQLiteCaseStore(tmp_path / "cases.sqlite3")
    store.initialize()
    persist_audited_case(store, prefix)
    admitted_at = run.execution_completed_at + timedelta(seconds=1)
    bundle = run.evidence_bundle(
        bundle_id="bundle_fixture",
        case_id=case.case_id,
        workflow_revision=5,
        constitution_id=case.constitution.constitution_id,
        constitution_hash=case.constitution.constitution_hash,
        amendment_chain_hash=amendment_chain_hash(case.amendments),
        previous_bundle_hash="0" * 64,
        admitted_at=admitted_at,
    )
    approved = adapter.approved_fixture_identity()
    context = EvidenceAdmissionContext(
        case_id=case.case_id,
        workflow_revision=5,
        constitution_id=case.constitution.constitution_id,
        constitution_hash=case.constitution.constitution_hash,
        amendment_chain_hash=amendment_chain_hash(case.amendments),
        engine=approved.engine,
        configuration_sha256=approved.configuration_sha256,
        input_artifacts=approved.input_semantics,
        input_artifact_observations=approved.input_observations,
        now=admitted_at,
    )
    (run.output_root / "extra.csv").write_text("value\n1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="standalone"):
        admit_engine_evidence(
            store,
            bundle,
            context,
            run.output_root,
            evidence_id="evidence_engine_fixture",
        )
    inspection = store.inspect()
    assert inspection.bundle_count == 0
    assert inspection.event_count == 5


def test_phase2a_cli_store_engine_admission_and_export_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository, executable, work_root = _fake_environment(tmp_path / "adapter")
    digest = _sha256(executable)
    monkeypatch.setattr(cli_module, "LocalCppV1Adapter", FixtureAdapter)
    engine_arguments = [
        "--repository",
        str(repository),
        "--executable",
        str(executable),
        "--expected-executable-sha256",
        digest,
        "--work-root",
        str(work_root),
    ]

    empty_store = tmp_path / "empty.sqlite3"
    assert main(["store", "init", str(empty_store)]) == 0
    assert main(["store", "inspect", str(empty_store)]) == 0
    assert main(["store", "validate", str(empty_store)]) == 0
    assert main(["store", "migrate", str(empty_store), "--dry-run"]) == 0

    complete_store = tmp_path / "complete.sqlite3"
    assert main(["store", "init", str(complete_store)]) == 0
    assert (
        main(
            [
                "case",
                "persist-demo",
                "--store",
                str(complete_store),
                "--scenario",
                "fragile",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "case",
                "reconstruct",
                "--store",
                str(complete_store),
                "--case-id",
                "case_fragile",
                "--require-complete",
            ]
        )
        == 0
    )
    package = tmp_path / "package"
    assert (
        main(
            [
                "case",
                "export",
                "--store",
                str(complete_store),
                "--case-id",
                "case_fragile",
                "--output-dir",
                str(package),
            ]
        )
        == 0
    )
    assert main(["case", "verify-package", str(package)]) == 0

    fixture_store = tmp_path / "fixture.sqlite3"
    assert main(["store", "init", str(fixture_store)]) == 0
    assert (
        main(
            [
                "case",
                "initialize-fixture",
                "--store",
                str(fixture_store),
                "--scenario",
                "provisional",
            ]
        )
        == 0
    )
    assert main(["engine", "verify-release", *engine_arguments]) == 0
    bundle_path = tmp_path / "bundle.json"
    capsys.readouterr()
    assert (
        main(
            [
                "engine",
                "execute-fixture",
                *engine_arguments,
                "--store",
                str(fixture_store),
                "--case-id",
                "case_provisional",
                "--bundle-output",
                str(bundle_path),
            ]
        )
        == 0
    )
    execution = json.loads(capsys.readouterr().out.strip())
    artifact_root = execution["artifact_root"]
    evidence_arguments = [
        *engine_arguments,
        "--store",
        str(fixture_store),
        "--case-id",
        "case_provisional",
        "--bundle-file",
        str(bundle_path),
        "--artifact-root",
        artifact_root,
    ]
    assert main(["evidence", "verify", *evidence_arguments]) == 0
    assert (
        main(
            [
                "evidence",
                "admit",
                *evidence_arguments,
                "--evidence-id",
                "evidence_cpp_cli",
            ]
        )
        == 2
    )
    assert (
        main(
            [
                "engine",
                "execute-and-admit-fixture",
                *engine_arguments,
                "--store",
                str(fixture_store),
                "--case-id",
                "case_provisional",
                "--evidence-id",
                "evidence_cpp_cli",
                "--bundle-output",
                str(tmp_path / "trusted-bundle.json"),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "case",
                "reconstruct",
                "--store",
                str(fixture_store),
                "--case-id",
                "case_provisional",
            ]
        )
        == 0
    )


def test_phase2a_cli_rejects_engine_execution_without_locked_constitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository, executable, work_root = _fake_environment(tmp_path / "adapter")
    monkeypatch.setattr(cli_module, "LocalCppV1Adapter", FixtureAdapter)
    store = tmp_path / "complete.sqlite3"
    assert main(["store", "init", str(store)]) == 0
    assert (
        main(
            [
                "case",
                "persist-demo",
                "--store",
                str(store),
                "--scenario",
                "provisional",
            ]
        )
        == 0
    )
    capsys.readouterr()
    result = main(
        [
            "engine",
            "execute-fixture",
            "--repository",
            str(repository),
            "--executable",
            str(executable),
            "--expected-executable-sha256",
            _sha256(executable),
            "--work-root",
            str(work_root),
            "--store",
            str(store),
            "--case-id",
            "case_provisional",
            "--bundle-output",
            str(tmp_path / "bundle.json"),
        ]
    )
    assert result == 2
    assert "locked constitution" in capsys.readouterr().err
