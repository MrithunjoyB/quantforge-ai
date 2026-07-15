#!/usr/bin/env python3
"""Inspect QuantForge wheel and sdist contents, metadata, and archive integrity."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import sys
import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Any

from scripts.check_repository import project_version


def _safe_archive_name(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts and "\\" not in name


def _one(paths: list[Path], label: str) -> Path:
    if len(paths) != 1:
        raise RuntimeError(f"expected exactly one {label}, found {[path.name for path in paths]}")
    return paths[0]


def runtime_requirements(requirements: list[str]) -> list[str]:
    """Return only unconditional runtime requirements, excluding optional-extra markers."""
    return [requirement for requirement in requirements if "extra ==" not in requirement]


def inspect_wheel(wheel: Path, version: str) -> dict[str, Any]:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise RuntimeError("wheel contains duplicate archive members")
        if not all(_safe_archive_name(name) for name in names):
            raise RuntimeError("wheel contains an unsafe archive member")
        allowed_roots = {"quantforge", f"quantforge_ai-{version}.dist-info"}
        unexpected = sorted({PurePosixPath(name).parts[0] for name in names} - allowed_roots)
        if unexpected:
            raise RuntimeError(f"wheel contains unexpected top-level paths: {unexpected}")
        required_package = {
            "quantforge/__init__.py",
            "quantforge/_version.py",
            "quantforge/cli/main.py",
            "quantforge/workflow/demo.py",
        }
        missing_package = sorted(required_package - set(names))
        if missing_package:
            raise RuntimeError(f"wheel is missing package files: {missing_package}")

        dist_info = f"quantforge_ai-{version}.dist-info"
        metadata_name = f"{dist_info}/METADATA"
        record_name = f"{dist_info}/RECORD"
        for required in (metadata_name, record_name, f"{dist_info}/entry_points.txt"):
            if required not in names:
                raise RuntimeError(f"wheel is missing {required}")
        license_names = {name for name in names if name.startswith(f"{dist_info}/licenses/")}
        if not any(name.endswith("/LICENSE") for name in license_names):
            raise RuntimeError("wheel does not contain LICENSE")
        if not any(name.endswith("/NOTICE") for name in license_names):
            raise RuntimeError("wheel does not contain NOTICE")

        metadata = BytesParser().parsebytes(archive.read(metadata_name))
        if metadata["Name"] != "quantforge-ai" or metadata["Version"] != version:
            raise RuntimeError("wheel name/version metadata is inconsistent")
        if metadata["Requires-Python"] != ">=3.12":
            raise RuntimeError("wheel Python requirement is inconsistent")
        requirements = metadata.get_all("Requires-Dist", [])
        if runtime_requirements(requirements) != ["pydantic==2.12.5"]:
            raise RuntimeError("wheel runtime dependency metadata is inconsistent")
        if metadata["License-Expression"] != "Apache-2.0":
            raise RuntimeError("wheel license expression is inconsistent")

        record_rows = list(csv.reader(io.StringIO(archive.read(record_name).decode("utf-8"))))
        if {row[0] for row in record_rows} != set(names):
            raise RuntimeError("wheel RECORD inventory does not equal archive inventory")
        for name, encoded_hash, size in record_rows:
            if name == record_name:
                if encoded_hash or size:
                    raise RuntimeError("wheel RECORD self-entry must not contain a digest")
                continue
            data = archive.read(name)
            expected = "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(
                b"="
            ).decode("ascii")
            if encoded_hash != expected or size != str(len(data)):
                raise RuntimeError(f"wheel RECORD mismatch for {name}")

    return {
        "filename": wheel.name,
        "members": len(names),
        "metadata": "passed",
        "record_integrity": "passed",
        "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
    }


def inspect_sdist(sdist: Path, version: str) -> dict[str, Any]:
    with tarfile.open(sdist, mode="r:gz") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)):
            raise RuntimeError("sdist contains duplicate archive members")
        if not all(_safe_archive_name(name) for name in names):
            raise RuntimeError("sdist contains an unsafe archive member")
        if any(member.issym() or member.islnk() or member.isdev() for member in members):
            raise RuntimeError("sdist contains a link or device member")
        roots = {PurePosixPath(name).parts[0] for name in names}
        expected_root = f"quantforge_ai-{version}"
        if roots != {expected_root}:
            raise RuntimeError(f"sdist root is inconsistent: {sorted(roots)}")
        relative_names = {
            PurePosixPath(name).relative_to(expected_root).as_posix()
            for name in names
            if name != expected_root
        }
        required = {
            "README.md",
            "LICENSE",
            "NOTICE",
            "SECURITY.md",
            "CONTRIBUTING.md",
            "CHANGELOG.md",
            "CITATION.cff",
            "CODE_OF_CONDUCT.md",
            "SUPPORT.md",
            "docs/RELEASE_POLICY.md",
            "docs/RELEASE_NOTES_v0.1.0.md",
            "pyproject.toml",
            "src/quantforge/_version.py",
        }
        missing = sorted(required - relative_names)
        if missing:
            raise RuntimeError(f"sdist is missing publication files: {missing}")
        prohibited_parts = {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache"}
        if any(prohibited_parts.intersection(PurePosixPath(name).parts) for name in relative_names):
            raise RuntimeError("sdist contains local repository or cache material")
        if any(
            name.startswith(("audit/", "release/", "dist/", "build/")) for name in relative_names
        ):
            raise RuntimeError("sdist contains excluded audit or generated output")

    return {
        "filename": sdist.name,
        "members": len(names),
        "safe_archive": "passed",
        "sha256": hashlib.sha256(sdist.read_bytes()).hexdigest(),
    }


def inspect_distributions(root: Path, dist_dir: Path) -> dict[str, Any]:
    version = project_version(root)
    wheel = _one(sorted(dist_dir.glob("*.whl")), "wheel")
    sdist = _one(sorted(dist_dir.glob("*.tar.gz")), "sdist")
    expected_wheel = f"quantforge_ai-{version}-py3-none-any.whl"
    expected_sdist = f"quantforge_ai-{version}.tar.gz"
    if wheel.name != expected_wheel or sdist.name != expected_sdist:
        raise RuntimeError(
            f"distribution filenames differ from contract: {wheel.name}, {sdist.name}"
        )
    return {
        "sdist": inspect_sdist(sdist, version),
        "status": "passed",
        "version": version,
        "wheel": inspect_wheel(wheel, version),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        result = inspect_distributions(root, args.dist_dir.resolve())
        if args.report is not None:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
    except (OSError, RuntimeError, tarfile.TarError, zipfile.BadZipFile) as error:
        print(f"package inspection failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
