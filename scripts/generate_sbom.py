#!/usr/bin/env python3
"""Generate and validate a deterministic CycloneDX 1.6 runtime SBOM."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from cyclonedx.model import HashAlgorithm, HashType, Property
from cyclonedx.model.bom import Bom, BomMetaData
from cyclonedx.model.component import Component, ComponentType
from cyclonedx.model.dependency import Dependency
from cyclonedx.model.license import LicenseExpression
from cyclonedx.model.tool import ToolRepository
from cyclonedx.output.json import JsonV1Dot6
from packageurl import PackageURL

from scripts.check_repository import project_version

REQUIREMENT_RE = re.compile(r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\s\\]+)")
HASH_RE = re.compile(r"--hash=sha256:(?P<hash>[0-9a-f]{64})")


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_lock(lock: Path) -> dict[str, dict[str, Any]]:
    lines = lock.read_text(encoding="utf-8").splitlines()
    packages: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    for line in lines:
        match = REQUIREMENT_RE.match(line)
        if match is not None:
            name = _normalize(match.group("name"))
            current = {"name": name, "version": match.group("version"), "hashes": []}
            packages[name] = current
            continue
        if current is not None:
            hash_match = HASH_RE.search(line)
            if hash_match is not None:
                hashes = current["hashes"]
                if not isinstance(hashes, list):
                    raise RuntimeError("internal lock parser type failure")
                hashes.append(hash_match.group("hash"))
    if not packages or any(not package["hashes"] for package in packages.values()):
        raise RuntimeError("runtime lock is empty or contains an unhashed distribution")
    return packages


def _component(package: dict[str, Any]) -> Component:
    name = str(package["name"])
    version = str(package["version"])
    hashes = package["hashes"]
    if not isinstance(hashes, list):
        raise RuntimeError("invalid lock hash inventory")
    purl = PackageURL(type="pypi", name=name, version=version)
    properties = [
        Property(name="quantforge:allowed-distribution-sha256", value=str(digest))
        for digest in sorted(hashes)
    ]
    return Component(
        name=name,
        version=version,
        type=ComponentType.LIBRARY,
        bom_ref=purl.to_string(),
        purl=purl,
        properties=properties,
    )


def generate_sbom(
    root: Path,
    wheel: Path,
    runtime_lock: Path,
    source_commit: str,
    source_epoch: int,
) -> dict[str, Any]:
    version = project_version(root)
    wheel_hash = hashlib.sha256(wheel.read_bytes()).hexdigest()
    packages = parse_lock(runtime_lock)
    components = {name: _component(package) for name, package in packages.items()}
    if "pydantic" not in components:
        raise RuntimeError("runtime lock does not contain direct dependency pydantic")

    root_purl = PackageURL(type="pypi", name="quantforge-ai", version=version)
    root_component = Component(
        name="quantforge-ai",
        version=version,
        type=ComponentType.APPLICATION,
        bom_ref=root_purl.to_string(),
        purl=root_purl,
        description="Audited Phase 1 offline quantitative-research governance foundation",
        hashes=[HashType(alg=HashAlgorithm.SHA_256, content=wheel_hash)],
        licenses=[LicenseExpression("Apache-2.0")],
        properties=[Property(name="quantforge:source-commit", value=source_commit)],
    )
    timestamp = datetime.fromtimestamp(source_epoch, tz=UTC)
    serializer_version = importlib.metadata.version("cyclonedx-python-lib")
    serializer_purl = PackageURL(
        type="pypi", name="cyclonedx-python-lib", version=serializer_version
    )
    serializer_component = Component(
        name="cyclonedx-python-lib",
        version=serializer_version,
        group="OWASP Foundation",
        type=ComponentType.APPLICATION,
        bom_ref=f"tool:{serializer_purl.to_string()}",
        purl=serializer_purl,
    )
    metadata = BomMetaData(
        component=root_component,
        timestamp=timestamp,
        tools=ToolRepository(components=[serializer_component]),
        properties=[
            Property(
                name="quantforge:runtime-lock-sha256",
                value=hashlib.sha256(runtime_lock.read_bytes()).hexdigest(),
            )
        ],
    )

    dependency_graph = {
        "quantforge-ai": ["pydantic"],
        "pydantic": [
            "annotated-types",
            "pydantic-core",
            "typing-extensions",
            "typing-inspection",
        ],
        "pydantic-core": ["typing-extensions"],
        "typing-inspection": ["typing-extensions"],
    }
    dependencies: list[Dependency] = [
        Dependency(
            ref=root_component.bom_ref,
            dependencies=[Dependency(ref=components["pydantic"].bom_ref)],
        )
    ]
    for package_name, child_names in sorted(dependency_graph.items()):
        if package_name == "quantforge-ai":
            continue
        if package_name not in components:
            raise RuntimeError(
                f"runtime dependency graph references missing package {package_name}"
            )
        missing = sorted(set(child_names) - set(components))
        if missing:
            raise RuntimeError(f"runtime dependency graph references missing packages: {missing}")
        dependencies.append(
            Dependency(
                ref=components[package_name].bom_ref,
                dependencies=[
                    Dependency(ref=components[name].bom_ref) for name in sorted(child_names)
                ],
            )
        )

    serial = uuid5(
        NAMESPACE_URL,
        f"https://quantforge.local/sbom/{version}/{source_commit}/{wheel_hash}",
    )
    bom = Bom(
        components=components.values(),
        dependencies=dependencies,
        metadata=metadata,
        serial_number=serial,
        version=1,
    )
    raw = JsonV1Dot6(bom).output_as_string()
    document = json.loads(raw)
    if not isinstance(document, dict):
        raise RuntimeError("CycloneDX serializer returned a non-object")
    validate_sbom(document, version, source_commit, wheel_hash, set(components))
    return document


def validate_sbom(
    document: dict[str, Any],
    version: str,
    source_commit: str,
    wheel_hash: str,
    expected_dependencies: set[str],
) -> None:
    if document.get("bomFormat") != "CycloneDX" or document.get("specVersion") != "1.6":
        raise RuntimeError("SBOM is not CycloneDX 1.6")
    if not str(document.get("serialNumber", "")).startswith("urn:uuid:"):
        raise RuntimeError("SBOM serial number is invalid")
    metadata = document.get("metadata")
    if not isinstance(metadata, dict):
        raise RuntimeError("SBOM metadata is missing")
    root_component = metadata.get("component")
    if not isinstance(root_component, dict):
        raise RuntimeError("SBOM root component is missing")
    if root_component.get("name") != "quantforge-ai" or root_component.get("version") != version:
        raise RuntimeError("SBOM root component identity is inconsistent")
    hashes = root_component.get("hashes")
    if not isinstance(hashes, list) or {item.get("content") for item in hashes} != {wheel_hash}:
        raise RuntimeError("SBOM root component does not bind the wheel hash")
    properties = root_component.get("properties")
    if not isinstance(properties, list) or not any(
        item.get("name") == "quantforge:source-commit" and item.get("value") == source_commit
        for item in properties
    ):
        raise RuntimeError("SBOM root component does not bind the source commit")
    components = document.get("components")
    if not isinstance(components, list):
        raise RuntimeError("SBOM dependency components are missing")
    observed = {str(component.get("name")) for component in components}
    if observed != expected_dependencies:
        raise RuntimeError(f"SBOM runtime inventory differs from lock: observed={sorted(observed)}")
    if not isinstance(document.get("dependencies"), list):
        raise RuntimeError("SBOM dependency graph is missing")


def write_sbom(document: dict[str, Any], output: Path) -> str:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    output.write_text(payload, encoding="utf-8", newline="\n")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--runtime-lock", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-epoch", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if re.fullmatch(r"[0-9a-f]{40}", args.source_commit) is None:
        print("SBOM generation failed: source commit must be 40 lowercase hexadecimal characters")
        return 1
    root = Path(__file__).resolve().parents[1]
    try:
        document = generate_sbom(
            root,
            args.wheel.resolve(),
            args.runtime_lock.resolve(),
            args.source_commit,
            args.source_epoch,
        )
        digest = write_sbom(document, args.output.resolve())
    except (OSError, RuntimeError, ValueError) as error:
        print(f"SBOM generation failed: {error}", file=sys.stderr)
        return 1
    print(f"CycloneDX 1.6 SBOM: {args.output.name} sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
