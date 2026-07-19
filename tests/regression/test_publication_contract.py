from __future__ import annotations

import json
import os
import subprocess
import tomllib
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from quantforge import __version__
from quantforge.cli.main import main
from scripts.check_repository import project_version, validate_repository
from scripts.check_secrets import history_text
from scripts.demo_package_smoke import distribution_environment_builder
from scripts.generate_sbom import generate_sbom, write_sbom
from scripts.inspect_packages import runtime_requirements
from scripts.release_candidate import ReleaseValidationError, verify_remote_boundary
from scripts.wheel_smoke import runtime_environment_builder, validate_demo_result


def test_pytest_explicitly_targets_the_source_tree() -> None:
    root = Path(__file__).resolve().parents[2]
    configuration = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert configuration["tool"]["pytest"]["ini_options"]["pythonpath"] == ["src"]


def test_secret_history_scan_preserves_non_utf8_patch_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def completed_process(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del args
        assert kwargs["encoding"] == "latin-1"
        return subprocess.CompletedProcess([], 0, "history-\x8a-patch", "")

    monkeypatch.setattr("scripts.check_secrets.shutil.which", lambda _name: "/usr/bin/git")
    monkeypatch.setattr("scripts.check_secrets.subprocess.run", completed_process)
    assert history_text(tmp_path) == "history-\x8a-patch"


def test_wheel_smoke_venv_preserves_posix_shared_library_resolution() -> None:
    builder = runtime_environment_builder()
    assert builder.with_pip is True
    assert builder.symlinks is (os.name != "nt")


def test_governed_distribution_smoke_isolated_install_environment() -> None:
    builder = distribution_environment_builder()
    assert builder.with_pip is True
    assert builder.system_site_packages is True
    assert builder.symlinks is (os.name != "nt")


def test_wheel_smoke_requires_the_actual_terminal_workflow_state() -> None:
    validate_demo_result({"state": "CHAIR_EXPLANATION", "verdict": "FRAGILE"})
    with pytest.raises(RuntimeError, match="unexpected governed result"):
        validate_demo_result({"state": "CLOSED", "verdict": "FRAGILE"})


def test_version_identity_is_single_source_and_cli_visible(
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = Path(__file__).resolve().parents[2]
    assert project_version(root) == __version__ == "0.1.0"
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == "quantforge 0.1.0"


def test_publication_repository_contract_is_complete() -> None:
    root = Path(__file__).resolve().parents[2]
    result = validate_repository(root)
    assert result["status"] == "passed"
    assert result["version"] == "0.1.0"
    assert result["local_links_checked"] > 10
    assert len(result["action_references"]) >= 10
    assert result["phase1_audit"]["status"] == "passed"
    assert result["phase1_audit"]["repaired_critical_high_medium"] == [
        "H-01",
        "H-02",
        "H-03",
        "H-04",
        "H-05",
        "M-01",
        "M-02",
        "M-03",
        "M-04",
    ]


def test_github_workflow_and_dependabot_yaml_is_well_formed() -> None:
    root = Path(__file__).resolve().parents[2]
    yaml = YAML(typ="safe")
    files = sorted((root / ".github/workflows").glob("*.yml"))
    files.append(root / ".github/dependabot.yml")
    for path in files:
        document = yaml.load(path.read_text(encoding="utf-8"))
        assert isinstance(document, dict), path


def test_release_candidate_remote_boundary_is_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = {
        ("remote",): "origin",
        ("remote", "get-url", "origin"): "https://github.com/MrithunjoyB/quantforge-ai",
        (
            "remote",
            "get-url",
            "--push",
            "origin",
        ): "https://github.com/MrithunjoyB/quantforge-ai",
    }
    monkeypatch.setattr("scripts.release_candidate.git_text", lambda _root, *args: commands[args])

    assert verify_remote_boundary(tmp_path, "https://github.com/MrithunjoyB/quantforge-ai.git") == [
        {
            "fetch_url": "https://github.com/MrithunjoyB/quantforge-ai",
            "name": "origin",
            "push_url": "https://github.com/MrithunjoyB/quantforge-ai",
        }
    ]
    with pytest.raises(ReleaseValidationError, match="does not match"):
        verify_remote_boundary(tmp_path, "https://github.com/MrithunjoyB/other")
    commands[("remote",)] = "origin\nunexpected"
    with pytest.raises(ReleaseValidationError, match="exactly one"):
        verify_remote_boundary(tmp_path, "https://github.com/MrithunjoyB/quantforge-ai")


def test_package_inspection_separates_runtime_and_optional_requirements() -> None:
    requirements = [
        "openai==2.46.0",
        "pydantic==2.12.5",
        "pytest==9.0.3; extra == 'dev'",
        "ruff==0.14.14; extra == 'dev'",
    ]
    assert runtime_requirements(requirements) == ["openai==2.46.0", "pydantic==2.12.5"]


def test_cyclonedx_sbom_generation_is_deterministic_and_versioned(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    wheel = tmp_path / "quantforge_ai-0.1.0-py3-none-any.whl"
    wheel.write_bytes(b"deterministic wheel fixture")
    first = generate_sbom(
        root,
        wheel,
        root / "requirements.lock",
        "a" * 40,
        1_752_556_800,
    )
    second = generate_sbom(
        root,
        wheel,
        root / "requirements.lock",
        "a" * 40,
        1_752_556_800,
    )
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    assert write_sbom(first, first_path) == write_sbom(second, second_path)
    assert first_path.read_bytes() == second_path.read_bytes()
    document = json.loads(first_path.read_text(encoding="utf-8"))
    assert document["bomFormat"] == "CycloneDX"
    assert document["specVersion"] == "1.6"
    assert document["metadata"]["component"]["version"] == "0.1.0"
