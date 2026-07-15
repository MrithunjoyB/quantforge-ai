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


def test_synthetic_package_fixtures_are_declared_resources() -> None:
    fixture_root = Path(__file__).resolve().parents[2] / "src/quantforge/adapters/fixtures"
    assert {path.name for path in fixture_root.glob("*.json")} == {
        "fragile.json",
        "inconclusive.json",
        "provisional.json",
    }
