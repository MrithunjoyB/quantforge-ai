from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_critical_coverage import CRITICAL_ROOTS


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
