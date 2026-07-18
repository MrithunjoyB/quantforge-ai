from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_critical_coverage import CRITICAL_FILES, CRITICAL_ROOTS


@pytest.mark.parametrize("undercovered_root", ["engine", "storage"])
def test_critical_coverage_command_fails_for_omitted_boundary_paths(
    tmp_path: Path, undercovered_root: str
) -> None:
    files: dict[str, object] = {}
    for root in CRITICAL_ROOTS:
        is_undercovered = root == f"src/quantforge/{undercovered_root}/"
        files[f"{root}fixture.py"] = {
            "summary": {
                "covered_branches": 0 if is_undercovered else 2,
                "covered_lines": 0 if is_undercovered else 8,
                "num_branches": 20 if is_undercovered else 2,
                "num_statements": 80 if is_undercovered else 8,
            }
        }
    for name in CRITICAL_FILES:
        files[name] = {
            "summary": {
                "covered_branches": 2,
                "covered_lines": 8,
                "num_branches": 2,
                "num_statements": 8,
            }
        }
    coverage_path = tmp_path / f"{undercovered_root}.json"
    coverage_path.write_text(json.dumps({"files": files}), encoding="utf-8")
    result = subprocess.run(  # noqa: S603 - fixed interpreter and test-owned arguments
        (
            sys.executable,
            "-m",
            "scripts.check_critical_coverage",
            "--coverage-json",
            str(coverage_path),
            "--minimum",
            "90",
        ),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "below 90.00%" in result.stderr


@pytest.mark.parametrize("undercovered_file", CRITICAL_FILES)
def test_security_critical_file_cannot_hide_inside_combined_coverage(
    tmp_path: Path,
    undercovered_file: str,
) -> None:
    files: dict[str, object] = {
        f"{root}fixture.py": {
            "summary": {
                "covered_branches": 100,
                "covered_lines": 400,
                "num_branches": 100,
                "num_statements": 400,
            }
        }
        for root in CRITICAL_ROOTS
    }
    for name in CRITICAL_FILES:
        undercovered = name == undercovered_file
        files[name] = {
            "summary": {
                "covered_branches": 0 if undercovered else 20,
                "covered_lines": 0 if undercovered else 80,
                "num_branches": 20,
                "num_statements": 80,
            }
        }
    coverage_path = tmp_path / "critical-file.json"
    coverage_path.write_text(json.dumps({"files": files}), encoding="utf-8")
    result = subprocess.run(  # noqa: S603 - fixed interpreter and test-owned arguments
        (
            sys.executable,
            "-m",
            "scripts.check_critical_coverage",
            "--coverage-json",
            str(coverage_path),
            "--minimum",
            "90",
        ),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert undercovered_file in result.stderr
