"""Narrow local adapter for the protected C++ v1.0.0 command-line release."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final

from quantforge.engine.base import ApprovedFixtureIdentity, EngineAdapter, EngineRun
from quantforge.engine.trust import (
    TrustedEngineExecution,
    _issue_trusted_execution_receipt,
)
from quantforge.evidence.bundle import (
    APPROVED_ARGUMENTS,
    CPP_PEELED_TARGET,
    CPP_TAG_OBJECT,
    MAX_ARTIFACT_BYTES,
    ArtifactObservation,
    ArtifactSemanticIdentity,
    EngineIdentity,
    InvocationIdentity,
    NumericFactReference,
    ValidatorResult,
    artifact_semantic_sha256,
)
from quantforge.serialization.canonical import canonical_decimal, canonical_sha256
from quantforge.serialization.safe_json import reject_symlink_components

APPROVED_CONFIG: Final = Path("configs/portfolio_equal_weight.json")
APPROVED_INPUTS: Final = tuple(
    Path(path)
    for path in (
        "data/synthetic/SYN_BENCH.csv",
        "data/synthetic/SYN_CRYPTO.csv",
        "data/synthetic/SYN_EQ_A.csv",
        "data/synthetic/SYN_EQ_B.csv",
        "data/synthetic/SYN_EQ_C.csv",
        "data/synthetic/metadata.json",
    )
)
APPROVED_VALIDATOR: Final = Path("scripts/validate_results.py")
MAX_PROCESS_OUTPUT_BYTES: Final = 1_000_000
MAX_RUN_SECONDS: Final = 300
MAX_VERSION_SECONDS: Final = 10
MAX_OUTPUT_FILES: Final = 256
MAX_CSV_ROWS: Final = 2_000_000
MAX_REPOSITORY_FILES: Final = 100_000
MAX_REPOSITORY_FILE_BYTES: Final = 128 * 1024 * 1024
_EXPECTED_REMOTE_URLS: Final = {
    "https://github.com/MrithunjoyB/cpp-event-driven-backtester",
    "https://github.com/MrithunjoyB/cpp-event-driven-backtester.git",
    "git@github.com:MrithunjoyB/cpp-event-driven-backtester.git",
}
_NONFINITE: Final = {
    "nan",
    "+nan",
    "-nan",
    "inf",
    "+inf",
    "-inf",
    "infinity",
    "+infinity",
    "-infinity",
}


@dataclass(frozen=True)
class _ProcessResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True)
class _StagedSnapshot:
    files: tuple[tuple[str, str, str, int, str], ...]


@dataclass(frozen=True)
class _RepositorySnapshot:
    repository_root: str
    git_common_directory: str
    remote: str
    head: str
    branch: str
    tag_object: str
    tag_target: str
    tag_type: str
    refs_sha256: str
    status_sha256: str
    tracked_diff_sha256: str
    staged_diff_sha256: str
    tracked_inventory_sha256: str
    untracked_inventory_sha256: str
    ignored_inventory_sha256: str


class LocalCppV1Adapter(EngineAdapter):
    """Stages one public synthetic fixture into an isolated, explicitly approved root."""

    def __init__(
        self,
        *,
        repository: Path,
        executable: Path,
        expected_executable_sha256: str,
        work_root: Path,
    ) -> None:
        if len(expected_executable_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in expected_executable_sha256
        ):
            raise ValueError("expected executable SHA-256 is malformed")
        self._repository = repository.absolute()
        self._executable = executable.absolute()
        self._expected_executable_sha256 = expected_executable_sha256
        self._work_root = work_root.absolute()

    @property
    def allowed_commands(self) -> tuple[tuple[str, ...], ...]:
        return (
            ("quant_cli", "version"),
            ("quant_cli", "validate-config", "--config", "configs/portfolio_equal_weight.json"),
            (
                "quant_cli",
                "print-resolved-config",
                "--config",
                "configs/portfolio_equal_weight.json",
            ),
            (
                "quant_cli",
                "run",
                "--config",
                "configs/portfolio_equal_weight.json",
                "--dry-run",
            ),
            ("quant_cli", *APPROVED_ARGUMENTS),
            ("python", "scripts/validate_results.py"),
        )

    def verify_release_identity(self) -> EngineIdentity:
        self._validate_repository_root()
        self._validate_work_root()
        remote = self._git("config", "--get", "remote.origin.url").stdout.decode().strip()
        if remote not in _EXPECTED_REMOTE_URLS:
            raise ValueError("protected engine remote identity is not approved")
        if self._git("status", "--porcelain=v1", "--untracked-files=all").stdout.strip():
            raise ValueError("protected engine tracked and untracked working tree is not clean")
        tag_object = self._git("rev-parse", "refs/tags/v1.0.0").stdout.decode().strip()
        tag_target = self._git("rev-parse", "refs/tags/v1.0.0^{}").stdout.decode().strip()
        tag_type = self._git("cat-file", "-t", "refs/tags/v1.0.0").stdout.decode().strip()
        if (tag_object, tag_target, tag_type) != (CPP_TAG_OBJECT, CPP_PEELED_TARGET, "tag"):
            raise ValueError(
                "protected engine v1.0.0 tag identity differs from the approved release"
            )
        approved_paths = (APPROVED_CONFIG, *APPROVED_INPUTS, APPROVED_VALIDATOR)
        diff = self._git(
            "diff",
            "--quiet",
            CPP_PEELED_TARGET,
            "--",
            *(path.as_posix() for path in approved_paths),
            allowed_returncodes={0, 1},
        )
        if diff.returncode != 0:
            raise ValueError("approved fixture or validator differs from the v1.0.0 release")
        self._validate_executable()
        identity = EngineIdentity(executable_sha256=_sha256_file(self._executable))
        with tempfile.TemporaryDirectory(
            prefix="quantforge-identity-", dir=self._work_root
        ) as identity_directory:
            identity_root = Path(identity_directory)
            version = self._run_bounded(
                (str(self._executable), "version"),
                cwd=identity_root,
                environment=self._minimal_environment(identity_root),
                timeout_seconds=MAX_VERSION_SECONDS,
                log_directory=None,
                log_name="version",
            )
        expected_lines = {
            "cpp-event-driven-backtester 1.0.0",
            "stochastic_methodology_version=2",
            "rng_mapping=portable_bounded_v1",
        }
        if set(version.stdout.decode("utf-8").splitlines()) != expected_lines:
            raise ValueError("engine executable version or methodology identity is not approved")
        return identity

    def execute_approved_fixture(self) -> EngineRun:
        run, _, _, _ = self._execute_fixture()
        return run

    def execute_trusted_fixture(
        self,
        *,
        case_id: str,
        workflow_revision: int,
        constitution_id: str,
        constitution_hash: str,
        amendment_chain_hash: str,
    ) -> TrustedEngineExecution:
        run, configuration_semantic, repository_snapshot_hash, validator_source_hash = (
            self._execute_fixture()
        )
        receipt = _issue_trusted_execution_receipt(
            run,
            case_id=case_id,
            workflow_revision=workflow_revision,
            constitution_id=constitution_id,
            constitution_hash=constitution_hash,
            amendment_chain_hash=amendment_chain_hash,
            configuration_semantic_sha256=configuration_semantic,
            repository_snapshot_sha256=repository_snapshot_hash,
            validator_source_sha256=validator_source_hash,
        )
        return TrustedEngineExecution(run=run, receipt=receipt)

    def _execute_fixture(self) -> tuple[EngineRun, str, str, str]:
        repository_before = self._repository_snapshot()
        identity = self.verify_release_identity()
        self._validate_work_root()
        if self._repository_snapshot() != repository_before:
            raise ValueError("protected engine repository changed during identity verification")
        run_root = Path(tempfile.mkdtemp(prefix="quantforge-engine-", dir=self._work_root))
        logs = run_root / ".adapter-logs"
        logs.mkdir(mode=0o700)
        environment = self._minimal_environment(run_root)
        input_semantics, input_observations = self._stage_inputs(run_root)
        staged_before = self._staged_snapshot(run_root)
        self._make_staged_inputs_read_only(run_root)
        configuration = run_root / APPROVED_CONFIG
        configuration_sha256 = _sha256_file(configuration)
        configuration_semantic_sha256 = artifact_semantic_sha256(configuration)
        validator_source_sha256 = _sha256_file(run_root / APPROVED_VALIDATOR)
        started_at = datetime.now(UTC)
        results: list[_ProcessResult] = []
        self._run_and_verify_engine(
            results,
            ("validate-config", "--config", APPROVED_CONFIG.as_posix()),
            run_root,
            environment,
            logs,
            "validate-config",
            staged_before,
        )
        self._run_and_verify_engine(
            results,
            ("print-resolved-config", "--config", APPROVED_CONFIG.as_posix()),
            run_root,
            environment,
            logs,
            "print-resolved-config",
            staged_before,
        )
        self._run_and_verify_engine(
            results,
            ("run", "--config", APPROVED_CONFIG.as_posix(), "--dry-run"),
            run_root,
            environment,
            logs,
            "dry-run",
            staged_before,
        )
        self._run_and_verify_engine(
            results,
            APPROVED_ARGUMENTS,
            run_root,
            environment,
            logs,
            "experiment",
            staged_before,
        )
        validator = self._run_bounded(
            (str(Path(sys.executable).resolve()), APPROVED_VALIDATOR.as_posix()),
            cwd=run_root,
            environment=environment,
            timeout_seconds=MAX_RUN_SECONDS,
            log_directory=logs,
            log_name="validate-results",
        )
        results.append(validator)
        self._verify_post_child_identity(run_root, staged_before)
        completed_at = datetime.now(UTC)
        self._verify_run_boundary(run_root)
        repository_after = self._repository_snapshot()
        if repository_after != repository_before:
            raise ValueError("protected engine repository boundary changed during execution")
        output_root = run_root / "results"
        output_semantics, output_observations = self._inventory_outputs(output_root)
        fact = self._extract_numeric_fact(output_root)
        validator_digest = hashlib.sha256(validator.stdout + b"\0" + validator.stderr).hexdigest()
        run = EngineRun(
            run_root=run_root,
            output_root=output_root,
            engine=identity,
            invocation=InvocationIdentity(),
            configuration_sha256=configuration_sha256,
            input_semantics=input_semantics,
            input_observations=input_observations,
            output_semantics=output_semantics,
            output_observations=output_observations,
            validators=(
                ValidatorResult(
                    name="validate_results",
                    status="passed",
                    output_sha256=validator_digest,
                ),
            ),
            numeric_facts=(fact,),
            execution_started_at=started_at,
            execution_completed_at=completed_at,
            stdout_sha256=_combined_digest(result.stdout for result in results),
            stderr_sha256=_combined_digest(result.stderr for result in results),
        )
        return (
            run,
            configuration_semantic_sha256,
            canonical_sha256(asdict(repository_before)),
            validator_source_sha256,
        )

    def approved_fixture_identity(self) -> ApprovedFixtureIdentity:
        engine = self.verify_release_identity()
        semantics: list[ArtifactSemanticIdentity] = []
        observations: list[ArtifactObservation] = []
        for relative in APPROVED_INPUTS:
            path = self._repository / relative
            schema = "json-v1" if path.suffix == ".json" else "csv-v1"
            semantics.append(
                ArtifactSemanticIdentity(
                    path=relative.as_posix(),
                    semantic_sha256=artifact_semantic_sha256(path),
                    schema_version=schema,
                )
            )
            observations.append(
                ArtifactObservation(
                    path=relative.as_posix(),
                    byte_sha256=_sha256_file(path),
                    size_bytes=path.stat().st_size,
                )
            )
        return ApprovedFixtureIdentity(
            engine=engine,
            configuration_sha256=_sha256_file(self._repository / APPROVED_CONFIG),
            input_semantics=tuple(sorted(semantics, key=lambda item: item.path)),
            input_observations=tuple(sorted(observations, key=lambda item: item.path)),
        )

    def _run_engine(
        self,
        arguments: tuple[str, ...],
        run_root: Path,
        environment: dict[str, str],
        logs: Path,
        log_name: str,
    ) -> _ProcessResult:
        approved = {command[1:] for command in self.allowed_commands if command[0] == "quant_cli"}
        if arguments not in approved:
            raise ValueError("engine invocation is outside the explicit command allow-list")
        return self._run_bounded(
            (str(self._executable), *arguments),
            cwd=run_root,
            environment=environment,
            timeout_seconds=MAX_RUN_SECONDS,
            log_directory=logs,
            log_name=log_name,
        )

    def _run_and_verify_engine(
        self,
        results: list[_ProcessResult],
        arguments: tuple[str, ...],
        run_root: Path,
        environment: dict[str, str],
        logs: Path,
        log_name: str,
        staged_before: _StagedSnapshot,
    ) -> None:
        results.append(self._run_engine(arguments, run_root, environment, logs, log_name))
        self._verify_post_child_identity(run_root, staged_before)

    def _verify_post_child_identity(self, run_root: Path, staged_before: _StagedSnapshot) -> None:
        if self._staged_snapshot(run_root) != staged_before:
            raise ValueError("staged configuration, input, or validator identity changed")
        self._validate_executable()
        validator = self._repository / APPROVED_VALIDATOR
        reject_symlink_components(validator)
        if validator.is_symlink() or not validator.is_file():
            raise ValueError("approved validator source identity changed")
        staged_validator = run_root / APPROVED_VALIDATOR
        if _sha256_file(validator) != _sha256_file(staged_validator):
            raise ValueError("approved validator source identity changed")

    def _staged_snapshot(self, run_root: Path) -> _StagedSnapshot:
        expected = {APPROVED_CONFIG, *APPROVED_INPUTS, APPROVED_VALIDATOR}
        allowed_directories = {
            parent for relative in expected for parent in relative.parents if parent != Path(".")
        }
        actual_files: set[Path] = set()
        for root_name in ("configs", "data", "scripts"):
            root = run_root / root_name
            reject_symlink_components(root)
            if root.is_symlink() or not root.is_dir():
                raise ValueError("staged input root is missing or has an unexpected file type")
            for candidate in sorted(root.rglob("*")):
                relative = candidate.relative_to(run_root)
                if candidate.is_symlink():
                    raise ValueError("staged input inventory contains a symlink")
                if candidate.is_dir():
                    if relative not in allowed_directories:
                        raise ValueError("staged input inventory contains an extra directory")
                    continue
                if not candidate.is_file():
                    raise ValueError("staged input inventory contains an unexpected file type")
                actual_files.add(relative)
        if actual_files != expected:
            missing = sorted(path.as_posix() for path in expected.difference(actual_files))
            extra = sorted(path.as_posix() for path in actual_files.difference(expected))
            raise ValueError(f"staged input inventory mismatch: missing={missing}, extra={extra}")
        files: list[tuple[str, str, str, int, str]] = []
        for relative in sorted(expected):
            path = run_root / relative
            schema = (
                "json-v1"
                if path.suffix.casefold() == ".json"
                else "csv-v1"
                if path.suffix.casefold() == ".csv"
                else "raw-v1"
            )
            byte_hash = _sha256_file(path)
            semantic_hash = artifact_semantic_sha256(path) if schema != "raw-v1" else byte_hash
            files.append(
                (relative.as_posix(), byte_hash, semantic_hash, path.stat().st_size, schema)
            )
        return _StagedSnapshot(tuple(files))

    @staticmethod
    def _make_staged_inputs_read_only(run_root: Path) -> None:
        for relative in (APPROVED_CONFIG, *APPROVED_INPUTS, APPROVED_VALIDATOR):
            with suppress(OSError):
                os.chmod(run_root / relative, 0o400)
        directories = sorted(
            {
                (run_root / relative).parent
                for relative in (APPROVED_CONFIG, *APPROVED_INPUTS, APPROVED_VALIDATOR)
            },
            key=lambda path: len(path.parts),
            reverse=True,
        )
        for directory in directories:
            with suppress(OSError):
                os.chmod(directory, 0o500)

    def _repository_snapshot(self) -> _RepositorySnapshot:
        repository_root = self._git("rev-parse", "--show-toplevel").stdout.decode().strip()
        git_common = self._git("rev-parse", "--git-common-dir").stdout.decode().strip()
        remote = self._git("config", "--get", "remote.origin.url").stdout.decode().strip()
        head = self._git("rev-parse", "HEAD").stdout.decode().strip()
        branch = self._git("branch", "--show-current").stdout.decode().strip()
        tag_object = self._git("rev-parse", "refs/tags/v1.0.0").stdout.decode().strip()
        tag_target = self._git("rev-parse", "refs/tags/v1.0.0^{}").stdout.decode().strip()
        tag_type = self._git("cat-file", "-t", "refs/tags/v1.0.0").stdout.decode().strip()
        refs = self._git("for-each-ref", "--format=%(refname)%00%(objectname)%00").stdout
        status = self._git("status", "--porcelain=v1", "--untracked-files=all").stdout
        tracked_diff = self._git("diff", "--no-ext-diff", "--binary").stdout
        staged_diff = self._git("diff", "--cached", "--no-ext-diff", "--binary").stdout
        return _RepositorySnapshot(
            repository_root=repository_root,
            git_common_directory=git_common,
            remote=remote,
            head=head,
            branch=branch,
            tag_object=tag_object,
            tag_target=tag_target,
            tag_type=tag_type,
            refs_sha256=hashlib.sha256(refs).hexdigest(),
            status_sha256=hashlib.sha256(status).hexdigest(),
            tracked_diff_sha256=hashlib.sha256(tracked_diff).hexdigest(),
            staged_diff_sha256=hashlib.sha256(staged_diff).hexdigest(),
            tracked_inventory_sha256=self._repository_inventory_sha256("ls-files", "-z"),
            untracked_inventory_sha256=self._repository_inventory_sha256(
                "ls-files", "--others", "--exclude-standard", "-z"
            ),
            ignored_inventory_sha256=self._repository_inventory_sha256(
                "ls-files", "--others", "--ignored", "--exclude-standard", "-z"
            ),
        )

    def _repository_inventory_sha256(self, *arguments: str) -> str:
        raw = self._git(*arguments).stdout
        if raw and not raw.endswith(b"\0"):
            raise ValueError("protected repository path inventory is malformed")
        raw_paths = raw.removesuffix(b"\0").split(b"\0") if raw else []
        if len(raw_paths) > MAX_REPOSITORY_FILES:
            raise ValueError("protected repository file inventory exceeds its limit")
        digest = hashlib.sha256()
        repository_root = self._repository.resolve(strict=True)
        for raw_path in sorted(raw_paths):
            relative_text = os.fsdecode(raw_path)
            relative = Path(relative_text)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("protected repository inventory contains an unsafe path")
            path = self._repository / relative
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError("protected repository inventory contains a forbidden symlink")
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("protected repository inventory contains a forbidden file type")
            if metadata.st_size > MAX_REPOSITORY_FILE_BYTES:
                raise ValueError("protected repository file exceeds its snapshot limit")
            try:
                path.resolve(strict=True).relative_to(repository_root)
            except ValueError as error:
                raise ValueError("protected repository file escapes its boundary") from error
            digest.update(raw_path)
            digest.update(b"\0")
            digest.update(str(metadata.st_size).encode("ascii"))
            digest.update(b"\0")
            digest.update(_sha256_file(path).encode("ascii"))
            digest.update(b"\0")
        return digest.hexdigest()

    def _git(
        self,
        *arguments: str,
        allowed_returncodes: set[int] | None = None,
    ) -> _ProcessResult:
        result = self._run_bounded(
            ("/usr/bin/git", *arguments),
            cwd=self._repository,
            environment={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin", "TZ": "UTC"},
            timeout_seconds=MAX_VERSION_SECONDS,
            log_directory=None,
            log_name="git-read",
            require_success=False,
        )
        permitted = allowed_returncodes or {0}
        if result.returncode not in permitted:
            raise ValueError(f"protected engine identity command failed: {arguments[0]}")
        return result

    def _stage_inputs(
        self, run_root: Path
    ) -> tuple[tuple[ArtifactSemanticIdentity, ...], tuple[ArtifactObservation, ...]]:
        for relative in (APPROVED_CONFIG, *APPROVED_INPUTS, APPROVED_VALIDATOR):
            source = self._repository / relative
            destination = run_root / relative
            _copy_bounded_regular_file(source, destination)
        semantics: list[ArtifactSemanticIdentity] = []
        observations: list[ArtifactObservation] = []
        for relative in APPROVED_INPUTS:
            path = run_root / relative
            schema = "json-v1" if path.suffix == ".json" else "csv-v1"
            semantics.append(
                ArtifactSemanticIdentity(
                    path=relative.as_posix(),
                    semantic_sha256=artifact_semantic_sha256(path),
                    schema_version=schema,
                )
            )
            observations.append(
                ArtifactObservation(
                    path=relative.as_posix(),
                    byte_sha256=_sha256_file(path),
                    size_bytes=path.stat().st_size,
                )
            )
        return (
            tuple(sorted(semantics, key=lambda item: item.path)),
            tuple(sorted(observations, key=lambda item: item.path)),
        )

    def _inventory_outputs(
        self, output_root: Path
    ) -> tuple[tuple[ArtifactSemanticIdentity, ...], tuple[ArtifactObservation, ...]]:
        reject_symlink_components(output_root)
        if output_root.is_symlink() or not output_root.is_dir():
            raise ValueError("approved engine run did not create its declared output directory")
        semantics: list[ArtifactSemanticIdentity] = []
        observations: list[ArtifactObservation] = []
        files = [candidate for candidate in sorted(output_root.rglob("*")) if candidate.is_file()]
        if not files or len(files) > MAX_OUTPUT_FILES:
            raise ValueError("engine output file inventory is empty or exceeds its limit")
        for path in files:
            if path.is_symlink():
                raise ValueError("engine output contains an untrusted symlink")
            relative = path.relative_to(output_root).as_posix()
            schema = _validate_output_artifact(path)
            semantics.append(
                ArtifactSemanticIdentity(
                    path=relative,
                    semantic_sha256=artifact_semantic_sha256(path),
                    schema_version=schema,
                )
            )
            observations.append(
                ArtifactObservation(
                    path=relative,
                    byte_sha256=_sha256_file(path),
                    size_bytes=path.stat().st_size,
                )
            )
        return tuple(semantics), tuple(observations)

    def _extract_numeric_fact(self, output_root: Path) -> NumericFactReference:
        matches = list(output_root.rglob("portfolio_performance_summary.csv"))
        if len(matches) != 1:
            raise ValueError("approved fixture did not produce one portfolio summary")
        path = matches[0]
        relative = path.relative_to(output_root).as_posix()
        try:
            with path.open(encoding="utf-8", newline="") as stream:
                reader = csv.DictReader(stream, strict=True)
                if reader.fieldnames is None or len(reader.fieldnames) != len(
                    set(reader.fieldnames)
                ):
                    raise ValueError("portfolio summary has missing or duplicate headers")
                rows = list(reader)
        except (csv.Error, UnicodeError) as error:
            raise ValueError("portfolio summary CSV is malformed") from error
        if len(rows) != 1 or "total_return" not in rows[0]:
            raise ValueError("portfolio summary does not contain its admitted numeric fact")
        try:
            value = Decimal(rows[0]["total_return"])
            canonical_decimal(value)
        except (InvalidOperation, ValueError) as error:
            raise ValueError("portfolio summary total return is malformed") from error
        return NumericFactReference(
            fact_id="fact_portfolio_total_return",
            name="portfolio total return",
            artifact_path=relative,
            structured_location="/rows/0/total_return",
            value=value,
            unit="fraction",
            methodology_id="causal_daily_v3_stochastic_v2",
        )

    def _validate_repository_root(self) -> None:
        reject_symlink_components(self._repository)
        if self._repository.is_symlink() or not self._repository.is_dir():
            raise ValueError("protected engine repository must be a non-symlink directory")
        if not (self._repository / ".git").exists():
            raise ValueError("protected engine path is not a Git repository")

    def _validate_executable(self) -> None:
        reject_symlink_components(self._executable)
        if self._executable.is_symlink() or not self._executable.is_file():
            raise ValueError("engine executable must be a regular non-symlink file")
        metadata = self._executable.stat()
        if metadata.st_size > 128 * 1024 * 1024 or (
            os.name == "posix" and not metadata.st_mode & stat.S_IXUSR
        ):
            raise ValueError("engine executable is too large or is not executable")
        if _sha256_file(self._executable) != self._expected_executable_sha256:
            raise ValueError("engine executable SHA-256 differs from the approved identity")

    def _validate_work_root(self) -> None:
        reject_symlink_components(self._work_root)
        if self._work_root.is_symlink() or not self._work_root.is_dir():
            raise ValueError("engine work root must be an existing non-symlink directory")

    def _verify_run_boundary(self, run_root: Path) -> None:
        allowed_top_level = {
            ".adapter-logs",
            "configs",
            "data",
            "home",
            "matplotlib",
            "results",
            "scripts",
            "tmp",
        }
        for candidate in sorted(run_root.rglob("*")):
            if candidate.is_symlink():
                raise ValueError("engine run created or traversed a symlink")
            if not candidate.is_dir() and not candidate.is_file():
                raise ValueError("engine run created an unexpected filesystem entry")
            relative = candidate.relative_to(run_root)
            if relative.parts and relative.parts[0] not in allowed_top_level:
                raise ValueError("engine run wrote outside the approved output boundary")

    @staticmethod
    def _minimal_environment(root: Path) -> dict[str, str]:
        directories = {
            "HOME": root / "home",
            "TMPDIR": root / "tmp",
            "MPLCONFIGDIR": root / "matplotlib",
        }
        for directory in directories.values():
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        return {
            "HOME": str(directories["HOME"]),
            "LANG": "C",
            "LC_ALL": "C",
            "MPLCONFIGDIR": str(directories["MPLCONFIGDIR"]),
            "PATH": "/usr/bin:/bin",
            "PYTHONHASHSEED": "0",
            "TMPDIR": str(directories["TMPDIR"]),
            "TZ": "UTC",
        }

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
        if not argv or any("\x00" in argument for argument in argv):
            raise ValueError("process argument vector is malformed")
        if log_directory is not None:
            return _execute_process(
                argv,
                cwd=cwd,
                environment=environment,
                timeout_seconds=timeout_seconds,
                directory=log_directory,
                log_name=log_name,
                require_success=require_success,
            )
        with tempfile.TemporaryDirectory(prefix="quantforge-process-") as temporary:
            return _execute_process(
                argv,
                cwd=cwd,
                environment=environment,
                timeout_seconds=timeout_seconds,
                directory=Path(temporary),
                log_name=log_name,
                require_success=require_success,
            )


def _execute_process(
    argv: tuple[str, ...],
    *,
    cwd: Path,
    environment: dict[str, str],
    timeout_seconds: int,
    directory: Path,
    log_name: str,
    require_success: bool,
) -> _ProcessResult:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    stdout_path = directory / f"{log_name}.stdout"
    stderr_path = directory / f"{log_name}.stderr"
    with stdout_path.open("w+b") as stdout, stderr_path.open("w+b") as stderr:
        process = subprocess.Popen(  # noqa: S603 - immutable argv allow-list boundary
            argv,
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            shell=False,
            start_new_session=True,
        )
        deadline = time.monotonic() + timeout_seconds
        while process.poll() is None:
            if time.monotonic() >= deadline:
                _terminate_process(process)
                raise ValueError(f"approved process timed out: {Path(argv[0]).name}")
            if (
                stdout_path.stat().st_size > MAX_PROCESS_OUTPUT_BYTES
                or stderr_path.stat().st_size > MAX_PROCESS_OUTPUT_BYTES
            ):
                _terminate_process(process)
                raise ValueError(f"approved process exceeded output limits: {Path(argv[0]).name}")
            time.sleep(0.02)
        stdout.flush()
        stderr.flush()
        stdout.seek(0)
        stderr.seek(0)
        stdout_bytes = stdout.read(MAX_PROCESS_OUTPUT_BYTES + 1)
        stderr_bytes = stderr.read(MAX_PROCESS_OUTPUT_BYTES + 1)
    if len(stdout_bytes) > MAX_PROCESS_OUTPUT_BYTES or len(stderr_bytes) > MAX_PROCESS_OUTPUT_BYTES:
        raise ValueError("approved process exceeded output limits")
    result = _ProcessResult(argv, int(process.returncode), stdout_bytes, stderr_bytes)
    if require_success and result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace")[:500]
        raise ValueError(f"approved process failed with {result.returncode}: {detail}")
    return result


def _validate_output_artifact(path: Path) -> str:
    if path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError("engine output artifact exceeds its size limit")
    suffix = path.suffix.casefold()
    if suffix == ".json":
        value = _read_engine_json(path)
        version = value.get("result_schema_version") if isinstance(value, dict) else None
        if version is None:
            return "validated-v1"
        if type(version) is not int or version not in {1, 2, 3}:
            raise ValueError("engine JSON uses an unknown result schema version")
        return str(version)
    if suffix != ".csv":
        raise ValueError("approved fixture emitted an undeclared artifact type")
    versions: set[str] = set()
    try:
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            if reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames)):
                raise ValueError("engine CSV contains missing or duplicate headers")
            for index, row in enumerate(reader):
                if index >= MAX_CSV_ROWS:
                    raise ValueError("engine CSV exceeds its row limit")
                if None in row or any(value is None for value in row.values()):
                    raise ValueError("engine CSV contains a malformed row")
                if any(value.strip().casefold() in _NONFINITE for value in row.values()):
                    raise ValueError("engine CSV contains a non-finite value")
                schema = row.get("schema_version")
                if schema:
                    versions.add(schema)
    except (csv.Error, UnicodeError) as error:
        raise ValueError("engine CSV is malformed") from error
    if not versions:
        return "validated-v1"
    if len(versions) != 1 or not versions.issubset({"1", "2", "3"}):
        raise ValueError("engine CSV uses a mixed or unknown schema version")
    return next(iter(versions))


def _read_engine_json(path: Path) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON key in engine artifact: {key}")
            value[key] = item
        return value

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_float=Decimal,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite engine JSON value is forbidden: {token}")
            ),
        )
    except (json.JSONDecodeError, UnicodeError) as error:
        raise ValueError("engine JSON is malformed") from error
    _validate_json_depth(value)
    return value


def _validate_json_depth(value: Any, depth: int = 0) -> None:
    if depth > 64:
        raise ValueError("engine JSON nesting exceeds its resource limit")
    if isinstance(value, dict):
        for item in value.values():
            _validate_json_depth(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _validate_json_depth(item, depth + 1)


def _copy_bounded_regular_file(source: Path, destination: Path) -> None:
    reject_symlink_components(source)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError("approved engine input must be a bounded regular file")
    source_metadata = source.stat()
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    source_descriptor = os.open(source, flags)
    try:
        opened_metadata = os.fstat(source_descriptor)
        if (opened_metadata.st_dev, opened_metadata.st_ino) != (
            source_metadata.st_dev,
            source_metadata.st_ino,
        ):
            raise ValueError("approved engine input was replaced while staging")
        destination_descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        try:
            total = 0
            while True:
                block = os.read(source_descriptor, 128 * 1024)
                if not block:
                    break
                total += len(block)
                if total > MAX_ARTIFACT_BYTES:
                    raise ValueError("approved engine input exceeds its size limit")
                remaining = memoryview(block)
                while remaining:
                    written = os.write(destination_descriptor, remaining)
                    remaining = remaining[written:]
            os.fsync(destination_descriptor)
        finally:
            os.close(destination_descriptor)
    finally:
        os.close(source_descriptor)
    final_source = source.stat()
    if (final_source.st_dev, final_source.st_ino) != (
        source_metadata.st_dev,
        source_metadata.st_ino,
    ) or final_source.st_size != destination.stat().st_size:
        raise ValueError("approved engine input changed while staging")


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except PermissionError:
            process.kill()
        except ProcessLookupError:
            pass
    else:  # pragma: no cover - Windows-specific process termination
        process.kill()
    process.wait(timeout=5)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(128 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _combined_digest(parts: Iterable[bytes]) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part)
        digest.update(b"\0")
    return digest.hexdigest()


__all__ = ["APPROVED_CONFIG", "APPROVED_INPUTS", "LocalCppV1Adapter"]
