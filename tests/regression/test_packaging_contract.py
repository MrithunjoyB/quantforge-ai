from __future__ import annotations

import tomllib
from pathlib import Path


def test_packaging_metadata_and_editable_build_dependencies_exist() -> None:
    root = Path(__file__).resolve().parents[2]
    configuration = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert (root / configuration["project"]["readme"]).is_file()
    assert (root / "LICENSE").is_file()
    assert configuration["build-system"]["requires"] == [
        "editables==0.5",
        "hatchling==1.27.0",
    ]
    assert configuration["project"]["dynamic"] == ["version"]
    assert "version" not in configuration["project"]
    assert configuration["tool"]["hatch"]["version"]["path"] == "src/quantforge/_version.py"
    assert configuration["project"]["requires-python"] == ">=3.12"
    assert configuration["project"]["dependencies"] == [
        "openai==2.46.0",
        "pydantic==2.12.5",
    ]
    assert configuration["project"]["license"] == "Apache-2.0"
    assert configuration["project"]["license-files"] == ["LICENSE", "NOTICE"]
    assert configuration["tool"]["hatch"]["build"]["exclude"] == ["/audit"]
    assert configuration["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        "src/quantforge"
    ]
    assert configuration["project"]["optional-dependencies"]["dev"][:3] == [
        "build==1.5.0",
        "cffconvert==2.0.0",
        "cyclonedx-python-lib==9.1.0",
    ]


def test_synthetic_package_fixtures_are_declared_resources() -> None:
    fixture_root = Path(__file__).resolve().parents[2] / "src/quantforge/adapters/fixtures"
    assert {path.name for path in fixture_root.glob("*.json")} == {
        "fragile.json",
        "governed_tribunal.json",
        "inconclusive.json",
        "provisional.json",
    }


def test_runtime_and_development_locks_are_hash_complete() -> None:
    root = Path(__file__).resolve().parents[2]
    runtime = (root / "requirements.lock").read_text(encoding="utf-8")
    development = (root / "requirements-dev.lock").read_text(encoding="utf-8")
    assert "--hash=sha256:" in runtime
    assert "--hash=sha256:" in development
    for requirement in (
        "build==1.5.0",
        "cffconvert==2.0.0",
        "cyclonedx-python-lib==9.1.0",
        "editables==0.5",
        "hatchling==1.27.0",
        "mypy==1.19.1",
        "pip-audit==2.9.0",
        "pip-tools==7.5.2",
        "pytest==9.0.3",
        "pytest-cov==7.0.0",
        "ruff==0.14.14",
    ):
        assert requirement in development
