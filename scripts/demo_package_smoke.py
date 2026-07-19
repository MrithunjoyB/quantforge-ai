#!/usr/bin/env python3
"""Run the governed C++ tribunal from installed wheel and sdist environments."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import venv
from pathlib import Path
from typing import Any


def _venv_python(environment: Path) -> Path:
    if os.name == "nt":
        return environment / "Scripts/python.exe"
    return environment / "bin/python"


def distribution_environment_builder() -> venv.EnvBuilder:
    """Reuse the reviewed build/runtime dependencies but install QuantForge locally."""

    return venv.EnvBuilder(
        with_pip=True,
        system_site_packages=True,
        symlinks=os.name != "nt",
    )


def _run(argv: list[str], cwd: Path, environment: dict[str, str]) -> str:
    result = subprocess.run(  # noqa: S603 - controlled release paths and fixed argument vectors
        argv,
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        output = f"{result.stdout}{result.stderr}"
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(argv)}\n{output}")
    return result.stdout.strip()


def _smoke_distribution(
    distribution: Path,
    *,
    label: str,
    repository: Path,
    executable: Path,
    expected_executable_sha256: str,
    engine_work_root: Path,
    build_requirements_lock: Path,
    requirements_lock: Path,
    root: Path,
) -> dict[str, Any]:
    environment_root = root / f"{label}-venv"
    outside_source = root / f"{label}-outside-source"
    outside_source.mkdir()
    distribution_environment_builder().create(environment_root)
    python = _venv_python(environment_root)
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.update(
        {
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_CACHE_DIR": str(root / "pip-cache"),
            "PIP_NO_INPUT": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        }
    )
    _run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--require-hashes",
            "-r",
            str(build_requirements_lock if label == "sdist" else requirements_lock),
        ],
        outside_source,
        environment,
    )
    _run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-build-isolation",
            str(distribution),
        ],
        outside_source,
        environment,
    )
    _run([str(python), "-m", "pip", "check"], outside_source, environment)
    module_location = Path(
        _run(
            [
                str(python),
                "-c",
                "import pathlib, quantforge; print(pathlib.Path(quantforge.__file__).resolve())",
            ],
            outside_source,
            environment,
        )
    )
    try:
        module_location.relative_to(environment_root.resolve(strict=True))
    except ValueError as error:
        raise RuntimeError(
            "distribution smoke imported QuantForge outside its test environment"
        ) from error

    artifact_directory = outside_source / "governed-tribunal"
    summary = _run(
        [
            str(python),
            "-m",
            "quantforge",
            "demo",
            "run",
            "--repository",
            str(repository),
            "--executable",
            str(executable),
            "--expected-executable-sha256",
            expected_executable_sha256,
            "--work-root",
            str(engine_work_root),
            "--output-dir",
            str(artifact_directory),
        ],
        outside_source,
        environment,
    )
    verification = json.loads(
        _run(
            [
                str(python),
                "-m",
                "quantforge",
                "demo",
                "verify",
                str(artifact_directory),
            ],
            outside_source,
            environment,
        )
    )
    if (
        verification.get("valid") is not True
        or verification.get("verdict") != "INCONCLUSIVE"
        or verification.get("role_results") != 6
    ):
        raise RuntimeError("installed distribution returned an unexpected tribunal result")
    if "OFFLINE GOVERNED DEMONSTRATION — MOCK PROVIDER" not in summary:
        raise RuntimeError("installed distribution omitted the mandatory demonstration label")
    return {
        "artifact_directory": str(artifact_directory),
        "demonstration_semantic_sha256": verification["demonstration_semantic_sha256"],
        "distribution": distribution.name,
        "import_location": str(module_location),
        "outside_source_tree": True,
        "status": "passed",
        "verdict": verification["verdict"],
    }


def smoke_distributions(
    wheel: Path,
    sdist: Path,
    *,
    repository: Path,
    executable: Path,
    expected_executable_sha256: str,
    engine_work_root: Path,
    build_requirements_lock: Path,
    requirements_lock: Path,
    work_directory: Path,
) -> dict[str, Any]:
    if work_directory.exists():
        raise RuntimeError(f"distribution smoke work directory already exists: {work_directory}")
    if not all(
        path.is_file() for path in (wheel, sdist, build_requirements_lock, requirements_lock)
    ):
        raise RuntimeError("distributions and hash-locked requirements must exist")
    if not repository.is_dir() or not executable.is_file() or not engine_work_root.is_dir():
        raise RuntimeError("engine repository, executable, or work root is unavailable")
    work_directory.mkdir(parents=True)
    wheel_result = _smoke_distribution(
        wheel,
        label="wheel",
        repository=repository,
        executable=executable,
        expected_executable_sha256=expected_executable_sha256,
        engine_work_root=engine_work_root,
        build_requirements_lock=build_requirements_lock,
        requirements_lock=requirements_lock,
        root=work_directory,
    )
    sdist_result = _smoke_distribution(
        sdist,
        label="sdist",
        repository=repository,
        executable=executable,
        expected_executable_sha256=expected_executable_sha256,
        engine_work_root=engine_work_root,
        build_requirements_lock=build_requirements_lock,
        requirements_lock=requirements_lock,
        root=work_directory,
    )
    if (
        wheel_result["demonstration_semantic_sha256"]
        != sdist_result["demonstration_semantic_sha256"]
    ):
        raise RuntimeError("wheel and source distribution produced different semantic results")
    return {
        "semantic_identity_match": True,
        "sdist": sdist_result,
        "status": "passed",
        "wheel": wheel_result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--sdist", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--expected-executable-sha256", required=True)
    parser.add_argument("--engine-work-root", type=Path, required=True)
    parser.add_argument("--build-requirements-lock", type=Path, required=True)
    parser.add_argument("--requirements-lock", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = smoke_distributions(
            args.wheel.resolve(),
            args.sdist.resolve(),
            repository=args.repository.resolve(),
            executable=args.executable.resolve(),
            expected_executable_sha256=args.expected_executable_sha256,
            engine_work_root=args.engine_work_root.resolve(),
            build_requirements_lock=args.build_requirements_lock.resolve(),
            requirements_lock=args.requirements_lock.resolve(),
            work_directory=args.work_dir.resolve(),
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"governed distribution smoke failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
