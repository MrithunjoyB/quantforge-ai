"""Closed evaluation export, independent score verification, and semantic replay."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import model_validator

from quantforge.domain.models import Identifier, Sha256, StrictModel
from quantforge.evaluation.models import (
    EVALUATION_LABEL,
    EvaluationRun,
    EvaluationSuite,
)
from quantforge.evaluation.scoring import aggregate_metrics, score_case
from quantforge.evaluation.suite import load_suite
from quantforge.serialization.canonical import canonical_json, canonical_sha256
from quantforge.serialization.safe_json import (
    reject_symlink_components,
    safe_load_json,
    safe_write_json,
    safe_write_text,
)

_ARTIFACTS = frozenset(
    {
        "benchmark-inventory.json",
        "comparison-report.json",
        "comparison-report.md",
        "evidence-manifest.json",
    }
)
_CLOSED_INVENTORY = _ARTIFACTS | {"export-manifest.json"}


class EvaluationExportManifest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    evaluation_label: str
    export_id: Identifier
    run_id: Identifier
    run_semantic_sha256: Sha256
    suite_semantic_sha256: Sha256
    artifacts: dict[str, Sha256]
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def manifest_is_exact(self) -> Self:
        if set(self.artifacts) != _ARTIFACTS:
            raise ValueError("evaluation export manifest inventory is not closed")
        values = self.model_dump(mode="python", exclude={"manifest_sha256"})
        if self.manifest_sha256 != canonical_sha256(values):
            raise ValueError("evaluation export manifest identity mismatch")
        return self


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _metric(value: object) -> str:
    observed = getattr(value, "value", None)
    return "unavailable" if observed is None else str(observed)


def render_human_report(run: EvaluationRun) -> str:
    rows = "\n".join(
        "| "
        + " | ".join(
            (
                metric.architecture.value,
                _metric(metric.defect_true_positive_rate),
                _metric(metric.defect_false_negative_rate),
                _metric(metric.clean_case_false_positive_rate),
                _metric(metric.precision),
                _metric(metric.recall),
                "unavailable" if metric.f1 is None else str(metric.f1),
                _metric(metric.critical_defect_detection_rate),
                _metric(metric.authority_violation_success_rate),
            )
        )
        + " |"
        for metric in run.metrics
    )
    architecture_lines = "\n".join(
        (
            "- `single_agent`: one structured proposal, review, and recommendation; no direct "
            "governance authority.",
            "- `planner_reviewer`: one planner, one reviewer, and at most one bounded revision; "
            "retries are not reviewers.",
            "- `quantforge_tribunal`: the real six-role request, schema, validation, persistence, "
            "workflow, provenance, replay, and code-owned verdict path.",
        )
    )
    call_counts = {
        architecture: sum(
            result.provider_call_count
            for result in run.results
            if result.architecture is architecture
        )
        for architecture in run.architectures
    }
    call_rows = "\n".join(
        f"- `{architecture.value}`: "
        f"{call_counts[architecture]} "
        "retained primary fixture calls; deterministic repeat verification executed the same "
        "bounded structure again."
        for architecture in run.architectures
    )
    return "\n".join(
        (
            f"# {run.evaluation_label}",
            "",
            "## Technical comparative-evaluation report",
            "",
            f"- Run: `{run.run_id}`.",
            f"- Suite: `{run.suite_id}` version `{run.suite_version}`.",
            f"- Suite semantic SHA-256: `{run.suite_semantic_sha256}`.",
            f"- Cases: `{len(run.benchmark_ids)}`; architectures: `{len(run.architectures)}`.",
            f"- Provider fixture: `{run.provider_identity}` / `{run.model_snapshot}`.",
            "",
            "## Architecture definitions",
            "",
            architecture_lines,
            "",
            "## Fairness controls",
            "",
            "Every architecture received the same falsifiable claim, public evidence inventory, "
            "provider class, model fixture, maximum context budget, and maximum output budget. "
            "Ground truth and scoring remained in code-owned resources and were absent from "
            "provider requests. QuantForge retained its genuine authority boundaries; the "
            "baselines were not given or denied advisory information to force an outcome.",
            "",
            "Unavoidable architecture differences are explicit: call count, role-specific schema "
            "partitioning, reviewer independence, governed persistence, and deterministic verdict "
            "authority.",
            "",
            "## Offline call inventory",
            "",
            call_rows,
            "",
            "## Primary metrics",
            "",
            "| Architecture | Defect TPR | Defect FNR | Clean FPR | Precision | Recall | F1 | "
            "Critical detection | Authority success |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
            rows,
            "",
            "The machine-readable report retains every requested component separately, including "
            "unsupported-claim acceptance, fabricated-evidence acceptance, evidence-reference "
            "precision, authority attempts and successes, substitution acceptance, duplicate "
            "transitions, reproducibility completeness, schema validity, refusal, and failure. "
            "No composite score is reported.",
            "",
            "## Interpretation boundary",
            "",
            "These values validate fixture routing, deterministic scoring, authority enforcement, "
            "persistence, replay, and report integrity. They do not measure model intelligence, "
            "reasoning quality, live latency, live token cost, provider refusals, or live "
            "structured-output reliability. Identical or high mock quality values are fixture "
            "properties, not evidence of global competitiveness.",
            "",
            "Comparative global competitiveness requires the later approved live OpenAI "
            "evaluation and, eventually, independent external reproduction.",
            "",
        )
    )


def benchmark_inventory(run: EvaluationRun, suite: EvaluationSuite) -> dict[str, object]:
    selected = {identifier for identifier in run.benchmark_ids}
    return {
        "schema_version": "1.0",
        "suite_id": suite.suite_id,
        "suite_version": suite.suite_version,
        "suite_semantic_sha256": suite.semantic_sha256,
        "cases": tuple(
            {
                "benchmark_id": case.benchmark_id,
                "case_version": case.case_version,
                "expected_status": case.expected_status,
                "public_input_sha256": case.public_input_sha256,
                "ground_truth_sha256": case.ground_truth_sha256,
                "provenance_sha256": case.provenance_sha256,
                "semantic_sha256": case.semantic_sha256,
            }
            for case in suite.cases
            if case.benchmark_id in selected
        ),
    }


def evidence_manifest(run: EvaluationRun) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "evaluation_label": run.evaluation_label,
        "run_id": run.run_id,
        "run_semantic_sha256": run.semantic_sha256,
        "presentation_cautions": (
            "Keep the offline deterministic mock-provider label visible in every capture.",
            "Do not describe fixture scores as model intelligence or global superiority.",
            "Do not describe controlled synthetic inputs as market evidence or profitability.",
            "Show component metrics; do not invent a composite ranking.",
            "State that live OpenAI benchmarking and external reproduction remain pending.",
        ),
        "suggested_capture_order": (
            "benchmark-inventory.json case identities and clean control",
            "comparison-report.json component metrics and authority outcomes",
            "comparison-report.md fairness and interpretation boundary",
            "export verification output and semantic replay output",
        ),
        "readme_claims_allowed": (
            "A versioned deterministic benchmark foundation exists.",
            "Exports are independently score-verifiable and tamper-evident.",
            "Baselines have no direct governance or execution authority.",
            "Offline mock results validate the harness rather than model quality.",
        ),
    }


def export_evaluation(
    run: EvaluationRun, suite: EvaluationSuite, output_directory: Path
) -> EvaluationExportManifest:
    output = output_directory.absolute()
    reject_symlink_components(output.parent)
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    reject_symlink_components(output)
    if output.exists():
        raise ValueError("evaluation export output already exists")
    with tempfile.TemporaryDirectory(
        prefix=".quantforge-evaluation-export-", dir=output.parent
    ) as temporary:
        root = Path(temporary) / "artifact"
        root.mkdir(mode=0o700)
        safe_write_json(root / "comparison-report.json", run)
        safe_write_text(root / "comparison-report.md", render_human_report(run))
        safe_write_json(root / "benchmark-inventory.json", benchmark_inventory(run, suite))
        safe_write_json(root / "evidence-manifest.json", evidence_manifest(run))
        hashes = {name: _sha256_file(root / name) for name in sorted(_ARTIFACTS)}
        values = {
            "schema_version": "1.0",
            "evaluation_label": run.evaluation_label,
            "export_id": f"evaluation_export_{canonical_sha256(hashes)[:20]}",
            "run_id": run.run_id,
            "run_semantic_sha256": run.semantic_sha256,
            "suite_semantic_sha256": suite.semantic_sha256,
            "artifacts": hashes,
        }
        manifest = EvaluationExportManifest.model_validate(
            {**values, "manifest_sha256": canonical_sha256(values)}
        )
        safe_write_json(root / "export-manifest.json", manifest)
        verify_evaluation_export(root, suite=suite)
        os.replace(root, output)
    return manifest


def _load_run(path: Path) -> EvaluationRun:
    return EvaluationRun.model_validate_json(canonical_json(safe_load_json(path)))


def verify_evaluation_export(
    directory: Path, *, suite: EvaluationSuite | None = None
) -> dict[str, Any]:
    root = directory.absolute()
    reject_symlink_components(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("evaluation export must be a regular directory")
    observed = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    if any(path.is_symlink() for path in root.rglob("*")):
        raise ValueError("evaluation export may not contain symlinks")
    if observed != _CLOSED_INVENTORY:
        raise ValueError("evaluation export has a missing or extra artifact")
    manifest = EvaluationExportManifest.model_validate_json(
        canonical_json(safe_load_json(root / "export-manifest.json"))
    )
    for name, expected in manifest.artifacts.items():
        if _sha256_file(root / name) != expected:
            raise ValueError(f"evaluation export artifact hash mismatch: {name}")
    active_suite = suite or load_suite()
    if manifest.suite_semantic_sha256 != active_suite.semantic_sha256:
        raise ValueError("evaluation export is bound to a different benchmark suite")
    run = _load_run(root / "comparison-report.json")
    if (
        run.evaluation_label != EVALUATION_LABEL
        or run.semantic_sha256 != manifest.run_semantic_sha256
        or run.run_id != manifest.run_id
    ):
        raise ValueError("evaluation report identity differs from its export manifest")
    case_by_id = {case.benchmark_id: case for case in active_suite.cases}
    expected_scores = tuple(
        score_case(case_by_id[result.benchmark_id], result) for result in run.results
    )
    if expected_scores != run.scores:
        raise ValueError("evaluation scores do not recompute from ground truth and results")
    expected_metrics = tuple(
        aggregate_metrics(
            architecture,
            tuple(case_by_id[identifier] for identifier in run.benchmark_ids),
            tuple(result for result in run.results if result.architecture is architecture),
            tuple(score for score in run.scores if score.architecture is architecture),
            {
                result.benchmark_id: bool(result.deterministic_consistent)
                for result in run.results
                if result.architecture is architecture
            },
        )
        for architecture in run.architectures
    )
    if expected_metrics != run.metrics:
        raise ValueError("evaluation metrics do not independently recompute")
    if (root / "comparison-report.md").read_text(encoding="utf-8") != render_human_report(run):
        raise ValueError("human comparison report does not match machine results")
    if canonical_json(safe_load_json(root / "benchmark-inventory.json")) != canonical_json(
        benchmark_inventory(run, active_suite)
    ):
        raise ValueError("benchmark inventory does not match the active suite")
    if canonical_json(safe_load_json(root / "evidence-manifest.json")) != canonical_json(
        evidence_manifest(run)
    ):
        raise ValueError("evaluation evidence manifest does not match the verified report")
    return {
        "valid": True,
        "evaluation_label": run.evaluation_label,
        "export_id": manifest.export_id,
        "run_id": run.run_id,
        "run_semantic_sha256": run.semantic_sha256,
        "suite_semantic_sha256": active_suite.semantic_sha256,
        "result_count": len(run.results),
        "score_count": len(run.scores),
    }


def replay_evaluation_export(directory: Path) -> dict[str, Any]:
    verification = verify_evaluation_export(directory)
    run = _load_run(directory / "comparison-report.json")
    semantic_outputs = tuple(
        {
            "architecture": result.architecture,
            "benchmark_id": result.benchmark_id,
            "result_semantic_sha256": result.semantic_sha256,
            "terminal_response_semantic_sha256": result.responses[-1].semantic_sha256,
        }
        for result in run.results
    )
    return {
        **verification,
        "accepted_semantic_outputs": semantic_outputs,
        "duplicate_transition_count": sum(
            result.duplicate_transition_count for result in run.results
        ),
        "durable_advancement_created": False,
    }


__all__ = [
    "EvaluationExportManifest",
    "benchmark_inventory",
    "evidence_manifest",
    "export_evaluation",
    "render_human_report",
    "replay_evaluation_export",
    "verify_evaluation_export",
]
