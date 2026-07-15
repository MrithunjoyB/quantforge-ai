#!/usr/bin/env python3
"""Install the release wheel outside the source tree and exercise its governed CLI."""

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


def _run(argv: list[str], cwd: Path, env: dict[str, str]) -> str:
    result = subprocess.run(  # noqa: S603 - argv is constructed from controlled release paths
        argv,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        output = f"{result.stdout}{result.stderr}"
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(argv)}\n{output}")
    return result.stdout.strip()


def smoke_wheel(
    wheel: Path, requirements_lock: Path, version: str, work_dir: Path
) -> dict[str, Any]:
    if work_dir.exists():
        raise RuntimeError(f"wheel smoke work directory already exists: {work_dir}")
    work_dir.mkdir(parents=True)
    environment = work_dir / "runtime-venv"
    outside_source = work_dir / "outside-source"
    outside_source.mkdir()
    venv.EnvBuilder(with_pip=True).create(environment)
    python = _venv_python(environment)
    env = os.environ.copy()
    env.update(
        {
            "PIP_CACHE_DIR": str(work_dir / "pip-cache"),
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INPUT": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
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
            str(requirements_lock),
        ],
        outside_source,
        env,
    )
    _run([str(python), "-m", "pip", "install", "--no-deps", str(wheel)], outside_source, env)
    pip_check = _run([str(python), "-m", "pip", "check"], outside_source, env)
    runtime_version = _run(
        [
            str(python),
            "-c",
            "import quantforge; print(quantforge.__version__)",
        ],
        outside_source,
        env,
    )
    if runtime_version != version:
        raise RuntimeError(f"installed runtime version is {runtime_version}, expected {version}")
    cli_version = _run([str(python), "-m", "quantforge", "--version"], outside_source, env)
    if cli_version != f"quantforge {version}":
        raise RuntimeError(f"installed CLI version is inconsistent: {cli_version}")

    bundle = outside_source / "demo"
    demo_output = _run(
        [
            str(python),
            "-m",
            "quantforge",
            "case",
            "run-demo",
            "--scenario",
            "fragile",
            "--output-dir",
            str(bundle),
        ],
        outside_source,
        env,
    )
    demo = json.loads(demo_output)
    if demo.get("verdict") != "FRAGILE" or demo.get("state") != "CLOSED":
        raise RuntimeError("installed wheel demo returned an unexpected governed result")
    _run(
        [
            str(python),
            "-m",
            "quantforge",
            "case",
            "validate",
            str(bundle / "case.json"),
            "--audit-file",
            str(bundle / "audit.jsonl"),
        ],
        outside_source,
        env,
    )
    audit_output = _run(
        [
            str(python),
            "-m",
            "quantforge",
            "audit",
            "verify",
            str(bundle / "audit.jsonl"),
        ],
        outside_source,
        env,
    )
    audit = json.loads(audit_output)
    if audit.get("events") != 12 or audit.get("valid") is not True:
        raise RuntimeError("installed wheel audit replay returned an unexpected result")

    return {
        "audit_events": 12,
        "audit_replay": "passed",
        "cli_version": cli_version,
        "demo_verdict": "FRAGILE",
        "outside_source_tree": True,
        "pip_check": pip_check,
        "runtime_version": runtime_version,
        "status": "passed",
        "wheel": wheel.name,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--requirements-lock", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        result = smoke_wheel(
            args.wheel.resolve(),
            args.requirements_lock.resolve(),
            args.version,
            args.work_dir.resolve(),
        )
        if args.report is not None:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"wheel smoke failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
