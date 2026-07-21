from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed interpreter and test-owned arguments
        (sys.executable, "-m", "quantforge", "evaluation", *arguments),
        check=False,
        capture_output=True,
        text=True,
    )


def test_evaluation_cli_lists_runs_exports_verifies_replays_and_reports(
    tmp_path: Path,
) -> None:
    listed = _run("list", "--subset", "judge")
    assert listed.returncode == 0, listed.stderr
    assert len(json.loads(listed.stdout)["cases"]) == 7

    machine = _run(
        "run-case",
        "--case",
        "qf-bm-024-sound-control",
        "--architecture",
        "single_agent",
    )
    assert machine.returncode == 0, machine.stderr
    assert len(json.loads(machine.stdout)["results"]) == 1

    export = tmp_path / "cli-evaluation"
    created = _run(
        "run-case",
        "--case",
        "qf-bm-001-look-ahead",
        "--architecture",
        "planner_reviewer",
        "--output-dir",
        str(export),
    )
    assert created.returncode == 0, created.stderr
    assert json.loads(created.stdout)["output_directory"] == str(export)

    verified = _run("verify-export", str(export))
    assert verified.returncode == 0, verified.stderr
    assert json.loads(verified.stdout)["valid"] is True
    replayed = _run("replay", str(export))
    assert replayed.returncode == 0, replayed.stderr
    assert json.loads(replayed.stdout)["durable_advancement_created"] is False

    human = _run("report", str(export), "--format", "human")
    assert human.returncode == 0, human.stderr
    assert "Technical comparative-evaluation report" in human.stdout
    report = _run("report", str(export), "--format", "machine")
    assert report.returncode == 0, report.stderr
    assert json.loads(report.stdout)["evaluation_label"].startswith("OFFLINE DETERMINISTIC")


def test_evaluation_cli_runs_judge_subset_and_prepares_live_plan() -> None:
    judged = _run(
        "run-suite",
        "--subset",
        "judge",
        "--architecture",
        "single_agent",
    )
    assert judged.returncode == 0, judged.stderr
    assert len(json.loads(judged.stdout)["results"]) == 7

    live = _run(
        "live-plan",
        "--subset",
        "judge",
        "--architecture",
        "quantforge_tribunal",
        "--model",
        "approved-openai-model-snapshot",
        "--input-price-per-million-usd",
        "1",
        "--output-price-per-million-usd",
        "2",
    )
    assert live.returncode == 0, live.stderr
    plan = json.loads(live.stdout)
    assert plan["maximum_call_count"] == 42
    assert plan["requires_explicit_operator_approval"] is True
