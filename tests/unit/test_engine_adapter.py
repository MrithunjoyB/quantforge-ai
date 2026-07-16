from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from quantforge.audit import AuditLog
from quantforge.cli import main as cli_module
from quantforge.cli.main import main
from quantforge.engine.local_cpp import (
    APPROVED_CONFIG,
    APPROVED_INPUTS,
    APPROVED_VALIDATOR,
    LocalCppV1Adapter,
    _ProcessResult,
    _read_engine_json,
    _validate_output_artifact,
)
from quantforge.evidence.bundle import (
    EngineIdentity,
    EvidenceAdmissionContext,
    HmacSha256TestSigner,
    amendment_chain_hash,
)
from quantforge.storage import (
    SQLiteCaseStore,
    admit_engine_evidence,
    persist_audited_case,
)
from quantforge.workflow.demo import run_demo


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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        "schema_version,total_return\\n3,0.125\\n", encoding="utf-8"
    )
    (output / "run_metadata.json").write_text(
        json.dumps({{"result_schema_version": 2, "run_timestamp_utc": "now"}}) + "\\n",
        encoding="utf-8",
    )
    print("experiment complete")
else:
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
        "fixture/portfolio_performance_summary.csv",
        "fixture/run_metadata.json",
    ]
    assert run.numeric_facts[0].value.is_finite()
    assert run.numeric_facts[0].value.as_tuple().exponent < 0
    assert run.validators[0].status == "passed"
    assert all(command[0] in {"python", "quant_cli"} for command in adapter.allowed_commands)
    assert not (adapter._repository / "results").exists()


def test_approved_fixture_identity_is_independent_of_staging(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    identity = adapter.approved_fixture_identity()
    assert identity.engine.executable_sha256 == _sha256(adapter._executable)
    assert identity.configuration_sha256 == _sha256(adapter._repository / APPROVED_CONFIG)
    assert [item.path for item in identity.input_semantics] == sorted(
        path.as_posix() for path in APPROVED_INPUTS
    )


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
    run = adapter.execute_approved_fixture()
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
        signer=signer,
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
    admitted = admit_engine_evidence(
        store,
        bundle,
        context,
        run.output_root,
        evidence_id="evidence_engine_fixture",
        signer=signer,
    )
    assert admitted.durable_case.revision == 6
    assert admitted.durable_case.case.state.value == "EXPERIMENT_EXECUTED"
    assert store.inspect().bundle_count == 1
    assert store.list_evidence_bundles(case.case_id) == (bundle,)
    store.verify()

    with pytest.raises(ValueError, match="locked, not-yet-executed"):
        admit_engine_evidence(
            store,
            bundle,
            context,
            run.output_root,
            evidence_id="evidence_duplicate",
            signer=signer,
        )


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
    with pytest.raises(ValueError, match="inventory"):
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
