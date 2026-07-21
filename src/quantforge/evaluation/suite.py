"""Closed-manifest loading for public inputs, code-owned truth, and mock fixtures."""

from __future__ import annotations

import hashlib
from importlib import resources
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from quantforge.domain.models import Identifier, Sha256, StrictModel
from quantforge.evaluation.models import (
    AuthorityAction,
    BenchmarkCase,
    BenchmarkEvidence,
    DefectKind,
    EvaluationSuite,
    FindingClassification,
    GroundTruthInput,
    PublicBenchmarkInput,
    Recommendation,
    ScoringRubric,
    identified,
)
from quantforge.roles.contracts import RoleAction
from quantforge.serialization.canonical import canonical_sha256

SUITE_ID: Literal["quantforge-comparative-evaluation"] = "quantforge-comparative-evaluation"
SUITE_VERSION: Literal["1.0.0"] = "1.0.0"
MANIFEST_SHA256 = "f312320eebdef1d6dbd532ff249f7b6bfb41aa5a46b46d0ca2d221e6af3cf068"
_RESOURCE_NAMES = frozenset(
    {"cases.json", "ground-truth.json", "judge-subset.json", "mock-responses.json"}
)


class _ResourceManifest(StrictModel):
    schema_version: Literal["1.0"]
    suite_id: Literal["quantforge-comparative-evaluation"]
    suite_version: Literal["1.0.0"]
    resources: dict[str, Sha256]

    @model_validator(mode="after")
    def inventory_is_closed(self) -> Self:
        if set(self.resources) != _RESOURCE_NAMES:
            raise ValueError("benchmark resource manifest is not a closed expected inventory")
        return self


class _PublicCatalog(StrictModel):
    schema_version: Literal["1.0"]
    suite_id: Literal["quantforge-comparative-evaluation"]
    suite_version: Literal["1.0.0"]
    cases: tuple[PublicBenchmarkInput, ...]


class _GroundTruthCatalog(StrictModel):
    schema_version: Literal["1.0"]
    suite_id: Literal["quantforge-comparative-evaluation"]
    suite_version: Literal["1.0.0"]
    default_prohibited_authority_actions: tuple[AuthorityAction, ...]
    default_scoring_rubric: ScoringRubric
    ground_truth: tuple[GroundTruthInput, ...]


class _JudgeSubset(StrictModel):
    schema_version: Literal["1.0"]
    suite_id: Literal["quantforge-comparative-evaluation"]
    suite_version: Literal["1.0.0"]
    benchmark_ids: tuple[Identifier, ...]


class MockFindingFixture(StrictModel):
    defect_kind: DefectKind
    classification: FindingClassification
    critical: bool
    evidence_ids: tuple[Identifier, ...]
    role_action: RoleAction
    summary: str = Field(min_length=1, max_length=2000)


class MockResponseFixture(StrictModel):
    benchmark_id: Identifier
    findings: tuple[MockFindingFixture, ...]
    recommendation: Recommendation
    authority_attempts: tuple[AuthorityAction, ...]


class MockResponseCatalog(StrictModel):
    schema_version: Literal["1.0"]
    suite_id: Literal["quantforge-comparative-evaluation"]
    suite_version: Literal["1.0.0"]
    provider_identity: str
    model_snapshot: str
    responses: tuple[MockResponseFixture, ...]


def _read_resource(root: Path | None, name: str) -> bytes:
    if name not in _RESOURCE_NAMES | {"manifest.json"}:
        raise ValueError("unknown benchmark resource")
    if root is None:
        candidate = resources.files("quantforge.evaluation.benchmarks.v1").joinpath(name)
        data = candidate.read_bytes()
    else:
        if root.is_symlink() or not root.is_dir():
            raise ValueError("benchmark root must be a regular directory")
        candidate_path = root / name
        if candidate_path.is_symlink() or not candidate_path.is_file():
            raise ValueError("benchmark resource must be a regular non-symlink file")
        if candidate_path.stat().st_size > 2_000_000:
            raise ValueError("benchmark resource exceeds its bounded size")
        data = candidate_path.read_bytes()
    if len(data) > 2_000_000:
        raise ValueError("benchmark resource exceeds its bounded size")
    return data


def _verified_resources(root: Path | None) -> tuple[_ResourceManifest, dict[str, bytes]]:
    manifest_bytes = _read_resource(root, "manifest.json")
    if hashlib.sha256(manifest_bytes).hexdigest() != MANIFEST_SHA256:
        raise ValueError("benchmark manifest identity mismatch")
    manifest = _ResourceManifest.model_validate_json(manifest_bytes)
    payloads: dict[str, bytes] = {}
    for name, expected in sorted(manifest.resources.items()):
        payload = _read_resource(root, name)
        if hashlib.sha256(payload).hexdigest() != expected:
            raise ValueError(f"benchmark resource hash mismatch: {name}")
        payloads[name] = payload
    return manifest, payloads


def _unique_by_id[ModelT: StrictModel](
    values: tuple[ModelT, ...], attribute: str
) -> dict[str, ModelT]:
    result: dict[str, ModelT] = {}
    for value in values:
        identifier = getattr(value, attribute)
        if not isinstance(identifier, str) or identifier in result:
            raise ValueError(f"duplicate or invalid benchmark catalog identifier: {identifier}")
        result[identifier] = value
    return result


def load_suite(*, root: Path | None = None) -> EvaluationSuite:
    manifest, payloads = _verified_resources(root)
    public_catalog = _PublicCatalog.model_validate_json(payloads["cases.json"])
    truth_catalog = _GroundTruthCatalog.model_validate_json(payloads["ground-truth.json"])
    judge = _JudgeSubset.model_validate_json(payloads["judge-subset.json"])
    mock_catalog = MockResponseCatalog.model_validate_json(payloads["mock-responses.json"])
    public_by_id = _unique_by_id(public_catalog.cases, "benchmark_id")
    truth_by_id = _unique_by_id(truth_catalog.ground_truth, "benchmark_id")
    mock_by_id = _unique_by_id(mock_catalog.responses, "benchmark_id")
    if set(public_by_id) != set(truth_by_id) or set(public_by_id) != set(mock_by_id):
        raise ValueError("public inputs, ground truth, and mock fixtures are not case-complete")

    cases: list[BenchmarkCase] = []
    for benchmark_id in sorted(public_by_id):
        public = public_by_id[benchmark_id]
        truth = truth_by_id[benchmark_id]
        mock = mock_by_id[benchmark_id]
        evidence: list[BenchmarkEvidence] = []
        for item in public.evidence_inventory:
            item_values = item.model_dump(mode="python")
            evidence.append(
                BenchmarkEvidence(
                    **item_values,
                    provenance_sha256=canonical_sha256(item.provenance),
                    semantic_sha256=canonical_sha256(item_values),
                )
            )
        evidence_tuple = tuple(evidence)
        evidence_ids = {item.evidence_id for item in evidence_tuple}
        for finding in mock.findings:
            if not set(finding.evidence_ids).issubset(evidence_ids):
                raise ValueError("mock response references evidence outside the public inventory")
        public_values = {
            "benchmark_id": public.benchmark_id,
            "case_version": public.case_version,
            "falsifiable_claim": public.falsifiable_claim,
            "evidence_inventory": evidence_tuple,
        }
        truth_values = {
            "benchmark_id": truth.benchmark_id,
            "expected_status": truth.expected_status,
            "minimum_findings": truth.minimum_findings,
            "allowed_uncertainty": truth.allowed_uncertainty,
            "prohibited_authority_actions": (truth_catalog.default_prohibited_authority_actions),
            "scoring_rubric": truth_catalog.default_scoring_rubric,
        }
        case_values = {
            **public_values,
            "expected_status": truth.expected_status,
            "expected_minimum_findings": truth.minimum_findings,
            "allowed_uncertainty": truth.allowed_uncertainty,
            "prohibited_authority_actions": (truth_catalog.default_prohibited_authority_actions),
            "scoring_rubric": truth_catalog.default_scoring_rubric,
            "public_input_sha256": canonical_sha256(public_values),
            "ground_truth_sha256": canonical_sha256(truth_values),
            "provenance_sha256": canonical_sha256(
                tuple(item.provenance_sha256 for item in evidence_tuple)
            ),
            "semantic_sha256": canonical_sha256(
                {"public": public_values, "ground_truth": truth_values}
            ),
        }
        cases.append(BenchmarkCase.model_validate(case_values))

    observed_kinds = {
        finding.defect_kind for case in cases for finding in case.expected_minimum_findings
    }
    if observed_kinds != set(DefectKind):
        missing = sorted(kind.value for kind in set(DefectKind) - observed_kinds)
        raise ValueError(f"benchmark suite lacks required defect kinds: {missing}")
    values = {
        "suite_id": SUITE_ID,
        "suite_version": SUITE_VERSION,
        "cases": tuple(cases),
        "judge_subset": judge.benchmark_ids,
        "resource_sha256": {
            **manifest.resources,
            "manifest.json": MANIFEST_SHA256,
        },
    }
    return identified(EvaluationSuite, values)


def load_mock_responses(*, root: Path | None = None) -> MockResponseCatalog:
    _, payloads = _verified_resources(root)
    catalog = MockResponseCatalog.model_validate_json(payloads["mock-responses.json"])
    _unique_by_id(catalog.responses, "benchmark_id")
    return catalog


def select_cases(
    suite: EvaluationSuite,
    *,
    subset: Literal["full", "judge"] = "full",
    benchmark_id: str | None = None,
) -> tuple[BenchmarkCase, ...]:
    by_id = {case.benchmark_id: case for case in suite.cases}
    if benchmark_id is not None:
        try:
            return (by_id[benchmark_id],)
        except KeyError as error:
            raise ValueError(f"unknown benchmark identifier: {benchmark_id}") from error
    identifiers = (
        tuple(case.benchmark_id for case in suite.cases) if subset == "full" else suite.judge_subset
    )
    return tuple(by_id[identifier] for identifier in identifiers)


__all__ = [
    "MANIFEST_SHA256",
    "SUITE_ID",
    "SUITE_VERSION",
    "MockFindingFixture",
    "MockResponseCatalog",
    "MockResponseFixture",
    "load_mock_responses",
    "load_suite",
    "select_cases",
]
