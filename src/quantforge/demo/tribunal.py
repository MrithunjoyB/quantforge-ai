"""Professional deterministic offline execution of the governed six-role tribunal."""

from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import Field, model_validator

from quantforge.adapters.governed_demo import GovernedTribunalMockProvider
from quantforge.audit import AuditLog
from quantforge.domain.constitution import create_human_approval, lock_constitution
from quantforge.domain.models import (
    AuditEvent,
    ClaimScope,
    EvidenceObject,
    EvidenceReference,
    EvidenceRelationship,
    FindingSeverity,
    ResearchClaim,
    RoleName,
    Sha256,
    StrictModel,
    TribunalCase,
    Verdict,
    VerdictEligibility,
    WorkflowState,
)
from quantforge.engine.base import EngineAdapter
from quantforge.engine.trust import TrustedReceiptRecord
from quantforge.evidence.bundle import EvidenceBundle, amendment_chain_hash
from quantforge.evidence.graph import ClaimGraph, EdgeType, GraphEdge, GraphNode, NodeType
from quantforge.evidence.ledger import EvidenceLedgerSnapshot
from quantforge.roles.contracts import RoleAction
from quantforge.roles.orchestrator import TribunalOrchestrator
from quantforge.roles.requests import EvidenceSummary
from quantforge.serialization.canonical import canonical_decimal, canonical_json, canonical_sha256
from quantforge.serialization.safe_json import (
    reject_symlink_components,
    safe_load_json,
    safe_write_json,
    safe_write_text,
)
from quantforge.storage import (
    SQLiteCaseStore,
    execute_and_admit_engine_evidence,
    export_durable_case,
    verify_case_package,
)
from quantforge.storage.base import ProviderInvocationRecord
from quantforge.storage.export import CasePackageManifest
from quantforge.verdict.policy import VerdictInputs, VerdictPolicy
from quantforge.workflow.machine import StateMachine

DEMONSTRATION_LABEL: Final = "OFFLINE GOVERNED DEMONSTRATION — MOCK PROVIDER"
CASE_ID: Final = "case_governed_tribunal"
CLAIM_ID: Final = "claim_governed_tribunal"
EVIDENCE_ID: Final = "evidence_cpp_v1_governed_tribunal"
_TIMELINE_START: Final = datetime(2098, 12, 1, tzinfo=UTC)
_EXPECTED_ROLE_ACTIONS: Final = (
    RoleAction.PROPOSE_PROTOCOL,
    RoleAction.REVIEW_METHODOLOGY,
    RoleAction.REVIEW_STATISTICS,
    RoleAction.REQUEST_CHALLENGE,
    RoleAction.REVIEW_REPRODUCIBILITY,
    RoleAction.EXPLAIN_VERDICT,
)


class DemoCaseSpecification(StrictModel):
    demonstration_label: Literal["OFFLINE GOVERNED DEMONSTRATION — MOCK PROVIDER"]
    schema_version: Literal["1.0"] = "1.0"
    case_id: str
    claim: str
    strategy_and_parameter_hypothesis: tuple[str, ...]
    benchmark: str
    transaction_cost_assumptions: tuple[str, ...]
    data_and_regime_scope: tuple[str, ...]
    controls: tuple[str, ...]
    statistical_criteria: tuple[str, ...]
    rejection_and_failure_conditions: tuple[str, ...]
    expected_evidence_inventory: tuple[str, ...]
    assumptions: tuple[str, ...]


class DemoReplayStatus(StrictModel):
    actions_replayed: tuple[RoleAction, ...]
    duplicate_transitions: Literal[0] = 0
    provider_invocations: int = Field(ge=6, le=6)
    audit_events: int = Field(ge=12, le=12)
    audit_replay_verified: Literal[True] = True
    store_integrity_verified: Literal[True] = True
    export_reconstruction_verified: Literal[True] = True


class DemoExportInventory(StrictModel):
    export_id: str
    manifest_hash: Sha256
    artifact_hashes: tuple[tuple[str, Sha256], ...]
    reconstruction_result: dict[str, Any]


class DemoSemanticIdentities(StrictModel):
    case_spec_sha256: Sha256
    case_sha256: Sha256
    case_revision_sha256: Sha256
    constitution_sha256: Sha256
    amendment_chain_sha256: Sha256
    engine_bundle_semantic_sha256: Sha256
    trusted_execution_semantic_sha256: Sha256
    configuration_semantic_sha256: Sha256
    validator_source_sha256: Sha256
    verdict_eligibility_sha256: Sha256
    chair_explanation_sha256: Sha256
    policy_input_provider_semantic_hashes: tuple[Sha256, ...]
    all_provider_semantic_hashes: tuple[Sha256, ...]
    demonstration_semantic_sha256: Sha256


class DemoTrustedExecutionIdentity(StrictModel):
    adapter_contract_version: Literal["cpp-v1-adapter/2.0"]
    case_id: str
    workflow_revision: int
    constitution_id: str
    constitution_hash: Sha256
    amendment_chain_hash: Sha256
    repository: str
    release: str
    annotated_tag_object: str = Field(pattern=r"^[0-9a-f]{40}$")
    peeled_target: str = Field(pattern=r"^[0-9a-f]{40}$")
    executable_sha256: Sha256
    configuration_sha256: Sha256
    configuration_semantic_sha256: Sha256
    invocation_contract_version: str
    repository_snapshot_sha256: Sha256
    validator_source_sha256: Sha256
    run_fingerprint: Sha256


class GovernedTribunalResult(StrictModel):
    demonstration_label: Literal["OFFLINE GOVERNED DEMONSTRATION — MOCK PROVIDER"]
    schema_version: Literal["1.0"] = "1.0"
    case: TribunalCase
    case_revision: int = Field(ge=12, le=12)
    case_revision_identity: Sha256
    timeline: tuple[AuditEvent, ...]
    role_results: tuple[ProviderInvocationRecord, ...]
    engine_bundle: EvidenceBundle
    trusted_execution_identity: DemoTrustedExecutionIdentity
    evidence: tuple[EvidenceObject, ...]
    verdict_eligibility: VerdictEligibility
    replay_status: DemoReplayStatus
    export_inventory: DemoExportInventory
    semantic_identities: DemoSemanticIdentities
    observational_identities: dict[str, Sha256]
    observational_variability: tuple[str, ...]
    limitations: tuple[str, ...]
    required_next_actions: tuple[str, ...]

    @model_validator(mode="after")
    def complete_and_internally_bound(self) -> GovernedTribunalResult:
        if self.case.state is not WorkflowState.CHAIR_EXPLANATION:
            raise ValueError("governed demonstration result is not complete")
        if self.case.verdict_eligibility != self.verdict_eligibility:
            raise ValueError("demonstration verdict differs from the durable case")
        accepted = tuple(
            record.accepted_result.semantic_hash
            for record in self.role_results
            if record.accepted_result is not None
        )
        if accepted != self.semantic_identities.all_provider_semantic_hashes:
            raise ValueError("demonstration provider semantic inventory mismatch")
        if tuple(record.action for record in self.role_results) != _EXPECTED_ROLE_ACTIONS:
            raise ValueError("demonstration role invocation order is incomplete")
        return self


class EvidenceHighlight(StrictModel):
    fact_id: str
    label: str
    value: Decimal
    unit: str
    interpretation: str


class DemoEvidenceManifest(StrictModel):
    demonstration_label: Literal["OFFLINE GOVERNED DEMONSTRATION — MOCK PROVIDER"]
    schema_version: Literal["1.0"] = "1.0"
    case_id: str
    claim: str
    outcome: Verdict
    lifecycle: tuple[str, ...]
    key_evidence: tuple[EvidenceHighlight, ...]
    semantic_identities: DemoSemanticIdentities
    export_inventory: DemoExportInventory
    presentation_cautions: tuple[str, ...]
    suggested_capture_order: tuple[str, ...]


class DemoArtifactManifest(StrictModel):
    demonstration_label: Literal["OFFLINE GOVERNED DEMONSTRATION — MOCK PROVIDER"]
    schema_version: Literal["1.0"] = "1.0"
    case_id: str
    demonstration_semantic_sha256: Sha256
    case_package_manifest_hash: Sha256
    artifacts: dict[str, Sha256]

    @model_validator(mode="after")
    def inventory_is_safe_and_sorted(self) -> DemoArtifactManifest:
        if list(self.artifacts) != sorted(self.artifacts):
            raise ValueError("demonstration artifact inventory must be sorted")
        for name in self.artifacts:
            path = Path(name)
            if path.is_absolute() or ".." in path.parts or len(path.parts) < 1:
                raise ValueError("demonstration artifact inventory contains an unsafe path")
        return self


def case_specification() -> DemoCaseSpecification:
    return DemoCaseSpecification(
        demonstration_label=DEMONSTRATION_LABEL,
        case_id=CASE_ID,
        claim=(
            "The frozen monthly equal-weight policy over five deterministic synthetic assets "
            "produces economically meaningful, statistically reliable outperformance over "
            "SYN_BENCH after declared costs, with acceptable drawdown and robustness."
        ),
        strategy_and_parameter_hypothesis=(
            "Causal MA-cross signals feed the frozen monthly equal-weight allocation policy.",
            (
                "Training uses three calendar years; evaluation uses six-month windows stepped "
                "every six months."
            ),
            "Maximum asset weight is 40 percent with a 2 percent cash buffer.",
            "No post-hoc parameter or candidate changes are permitted.",
        ),
        benchmark=(
            "SYN_BENCH under the same 2019-01-01 through 2025-12-31 causal union-calendar scope"
        ),
        transaction_cost_assumptions=(
            "10 basis points commission per fill",
            "5 basis points slippage per fill",
            "100000 USD starting capital",
            "next-open causal execution and monthly rebalancing",
        ),
        data_and_regime_scope=(
            "Only C++ v1.0.0 project-owned deterministic synthetic inputs are allowed.",
            "Universe: SYN_EQ_A, SYN_EQ_B, SYN_EQ_C, SYN_BENCH, and SYN_CRYPTO.",
            (
                "Synthetic bull, bear, sideways, high-volatility, and low-volatility regimes are "
                "inspected."
            ),
            "No downloaded, proprietary, live, or broker data is permitted.",
        ),
        controls=(
            "Immutable constitution before numerical execution",
            "Causal benchmark parity and explicit cost accounting",
            "Centered moving-block corrected reality check",
            "Drawdown, concentration, loss-probability, regime, and parameter challenges",
            "Independent reconstruction before reproducibility review",
        ),
        statistical_criteria=(
            "Corrected reality-check p-value below 0.05",
            "95 percent bootstrap return interval strictly above zero",
            "Bootstrap probability of positive active return at least 0.95",
            "Bootstrap probability of loss at most 0.10",
        ),
        rejection_and_failure_conditions=(
            "Corrected inference fails or remains unresolved",
            "Maximum drawdown is worse than minus 30 percent",
            "Loss probability exceeds 10 percent",
            "Material regime, concentration, parameter, or reproducibility gate fails",
            "Any required identity, artifact, validator, replay, or reconstruction check fails",
        ),
        expected_evidence_inventory=(
            "portfolio_performance_summary.csv",
            "portfolio_costs.csv",
            "attribution/portfolio_attribution_summary.csv",
            "attribution/regime_attribution.csv",
            "statistics/multiple_testing_summary.csv",
            "statistics/portfolio_policy_robustness.csv",
            "statistics/parameter_stability.csv",
            "statistics/sharpe_inference.csv",
            "run_metadata.json",
        ),
        assumptions=(
            "The protected C++ v1.0.0 engine is the numerical authority.",
            "Synthetic evidence can test governance and reproducibility, not live profitability.",
            (
                "Mock role outputs are advisory data and have no engine, evidence, workflow, or "
                "verdict authority."
            ),
        ),
    )


def run_governed_tribunal_demo(
    adapter: EngineAdapter,
    output_directory: Path,
) -> GovernedTribunalResult:
    """Run the real governed lifecycle and atomically publish its verified artifact set."""

    output = output_directory.absolute()
    reject_symlink_components(output.parent)
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    reject_symlink_components(output)
    if output.exists():
        raise ValueError("governed demonstration output already exists")
    with tempfile.TemporaryDirectory(
        prefix=".quantforge-governed-demo-", dir=output.parent
    ) as temp:
        root = Path(temp)
        artifact_root = root / "artifact"
        artifact_root.mkdir(mode=0o700)
        store = SQLiteCaseStore(root / "governed-tribunal.sqlite3")
        store.initialize()
        spec = case_specification()
        orchestrator = TribunalOrchestrator(GovernedTribunalMockProvider())
        _create_claim(store, spec)
        replayed_actions: list[RoleAction] = []
        _invoke_with_replay_probe(
            orchestrator,
            store,
            RoleAction.PROPOSE_PROTOCOL,
            _time(1),
            replayed_actions,
        )
        _invoke_with_replay_probe(
            orchestrator,
            store,
            RoleAction.REVIEW_METHODOLOGY,
            _time(2),
            replayed_actions,
        )
        _approve_and_lock(store)
        admitted = execute_and_admit_engine_evidence(
            store,
            adapter,
            case_id=CASE_ID,
            evidence_id=EVIDENCE_ID,
            admitted_at=_time(7),
        )
        evidence_summaries = _evidence_summaries(
            admitted.evidence_items, admitted.durable_case.case, 6
        )
        _invoke_with_replay_probe(
            orchestrator,
            store,
            RoleAction.REVIEW_STATISTICS,
            _time(8),
            replayed_actions,
            evidence_summaries=evidence_summaries,
        )
        _invoke_with_replay_probe(
            orchestrator,
            store,
            RoleAction.REQUEST_CHALLENGE,
            _time(9),
            replayed_actions,
            evidence_summaries=_revision_summaries(store, admitted.evidence_items, 7),
        )
        _enter_follow_up(store)
        reconstructed = store.reconstruct(CASE_ID, require_complete=False)
        if reconstructed.revision != 9 or store.verify().bundle_count != 1:
            raise ValueError("code-owned pre-review reconstruction did not match revision nine")
        _invoke_with_replay_probe(
            orchestrator,
            store,
            RoleAction.REVIEW_REPRODUCIBILITY,
            _time(11),
            replayed_actions,
            evidence_summaries=_revision_summaries(store, admitted.evidence_items, 9),
            code_owned_reproducibility_verified=True,
        )
        policy_hashes = orchestrator.semantic_hashes
        eligibility = _compute_verdict(store, policy_hashes)
        final_graph = _build_graph(store)
        _invoke_with_replay_probe(
            orchestrator,
            store,
            RoleAction.EXPLAIN_VERDICT,
            _time(13),
            replayed_actions,
            evidence_summaries=_revision_summaries(store, admitted.evidence_items, 11),
            final_claim_graph=final_graph,
        )
        durable = store.reconstruct(CASE_ID, require_complete=True)
        if durable.case.verdict_eligibility != eligibility:
            raise ValueError("durable verdict eligibility changed after Chair explanation")
        package = export_durable_case(store, CASE_ID, artifact_root / "case-package")
        reconstruction = verify_case_package(artifact_root / "case-package")
        store_inspection = store.verify()
        records = store.list_provider_invocations(CASE_ID)
        all_provider_hashes = tuple(
            record.accepted_result.semantic_hash
            for record in records
            if record.accepted_result is not None
        )
        trusted_execution = _trusted_execution_identity(admitted.trusted_receipt)
        case_spec_hash = canonical_sha256(spec)
        graph_hash = canonical_sha256(final_graph.snapshot())
        case_revision_identity = canonical_sha256(
            {
                "case_id": CASE_ID,
                "case_semantic_sha256": durable.semantic_hash,
                "revision": durable.revision,
            }
        )
        demo_semantic_hash = _demonstration_semantic_hash(
            spec_hash=case_spec_hash,
            case=durable.case,
            revision=durable.revision,
            timeline=durable.audit_log.events,
            bundle=admitted.bundle,
            provider_hashes=all_provider_hashes,
            trusted_execution=trusted_execution,
        )
        semantic_identities = DemoSemanticIdentities(
            case_spec_sha256=case_spec_hash,
            case_sha256=durable.semantic_hash,
            case_revision_sha256=case_revision_identity,
            constitution_sha256=_constitution_hash(durable.case),
            amendment_chain_sha256=amendment_chain_hash(durable.case.amendments),
            engine_bundle_semantic_sha256=admitted.bundle.semantic_hash,
            trusted_execution_semantic_sha256=_trusted_execution_semantic_hash(trusted_execution),
            configuration_semantic_sha256=trusted_execution.configuration_semantic_sha256,
            validator_source_sha256=trusted_execution.validator_source_sha256,
            verdict_eligibility_sha256=canonical_sha256(eligibility),
            chair_explanation_sha256=canonical_sha256(durable.case.chair_explanation),
            policy_input_provider_semantic_hashes=policy_hashes,
            all_provider_semantic_hashes=all_provider_hashes,
            demonstration_semantic_sha256=demo_semantic_hash,
        )
        export_inventory = DemoExportInventory(
            export_id=package.export_id,
            manifest_hash=package.manifest_hash,
            artifact_hashes=package.artifact_hashes,
            reconstruction_result=reconstruction,
        )
        result = GovernedTribunalResult(
            demonstration_label=DEMONSTRATION_LABEL,
            case=durable.case,
            case_revision=durable.revision,
            case_revision_identity=case_revision_identity,
            timeline=durable.audit_log.events,
            role_results=records,
            engine_bundle=admitted.bundle,
            trusted_execution_identity=trusted_execution,
            evidence=admitted.evidence_items,
            verdict_eligibility=eligibility,
            replay_status=DemoReplayStatus(
                actions_replayed=tuple(replayed_actions),
                provider_invocations=store_inspection.provider_invocation_count,
                audit_events=store_inspection.event_count,
            ),
            export_inventory=export_inventory,
            semantic_identities=semantic_identities,
            observational_identities={
                "audit_head_sha256": durable.audit_head_hash,
                "claim_graph_sha256": graph_hash,
                "engine_bundle_sha256": admitted.bundle.bundle_hash,
                "engine_observation_sha256": admitted.bundle.observation_hash,
                "export_manifest_sha256": package.manifest_hash,
                "repository_snapshot_sha256": trusted_execution.repository_snapshot_sha256,
                "run_fingerprint_sha256": trusted_execution.run_fingerprint,
            },
            observational_variability=(
                "Trusted execution start and completion timestamps",
                "Raw engine output byte hashes for explicitly observational JSON fields",
                "Repository snapshot identity includes host-local checkout paths and inventories",
                "Bundle, audit, graph, and export hashes that transitively bind those observations",
                (
                    "Stable semantic identities exclude only documented observations and remain "
                    "cross-checked"
                ),
            ),
            limitations=(
                (
                    "The role language is deterministic mock output and does not prove model "
                    "intelligence."
                ),
                "The numerical inputs are synthetic and do not prove live-market profitability.",
                "The result is research governance evidence, not financial advice or a forecast.",
                "Local hash chains are not externally signed or independently anchored.",
            ),
            required_next_actions=(
                (
                    "Preserve the INCONCLUSIVE verdict unless newly admitted evidence changes "
                    "policy inputs."
                ),
                (
                    "Perform a separately authorized live OpenAI contract verification before any "
                    "live-model claim."
                ),
                (
                    "Use the evidence manifest for presentation without implying real returns or "
                    "future performance."
                ),
            ),
        )
        evidence_manifest = _evidence_manifest(spec, result)
        safe_write_json(artifact_root / "case-spec.json", spec)
        safe_write_json(artifact_root / "tribunal-result.json", result)
        safe_write_json(artifact_root / "evidence-manifest.json", evidence_manifest)
        safe_write_text(artifact_root / "tribunal-report.md", _render_report(spec, result))
        artifact_hashes = _artifact_hashes(artifact_root)
        outer_manifest = DemoArtifactManifest(
            demonstration_label=DEMONSTRATION_LABEL,
            case_id=CASE_ID,
            demonstration_semantic_sha256=demo_semantic_hash,
            case_package_manifest_hash=package.manifest_hash,
            artifacts=artifact_hashes,
        )
        safe_write_json(artifact_root / "demo-manifest.json", outer_manifest)
        verify_governed_tribunal_demo(artifact_root)
        os.replace(artifact_root, output)
    return result


def verify_governed_tribunal_demo(directory: Path) -> dict[str, Any]:
    """Independently verify outer artifacts, durable replay, and semantic projection."""

    root = directory.absolute()
    reject_symlink_components(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("governed demonstration must be a regular non-symlink directory")
    manifest = DemoArtifactManifest.model_validate_json(
        canonical_json(safe_load_json(root / "demo-manifest.json"))
    )
    expected = {*manifest.artifacts, "demo-manifest.json"}
    actual: set[str] = set()
    for candidate in sorted(root.rglob("*")):
        if candidate.is_symlink():
            raise ValueError("governed demonstration contains a symlink")
        if candidate.is_dir():
            continue
        if not candidate.is_file():
            raise ValueError("governed demonstration contains an unsupported filesystem entry")
        actual.add(candidate.relative_to(root).as_posix())
    if actual != expected:
        raise ValueError(
            "governed demonstration artifact inventory is missing, extra, or substituted"
        )
    for name, expected_hash in manifest.artifacts.items():
        if _sha256_file(root / name) != expected_hash:
            raise ValueError(f"governed demonstration artifact hash mismatch: {name}")
    spec = DemoCaseSpecification.model_validate_json(
        canonical_json(safe_load_json(root / "case-spec.json"))
    )
    result = GovernedTribunalResult.model_validate_json(
        canonical_json(safe_load_json(root / "tribunal-result.json"))
    )
    evidence_manifest = DemoEvidenceManifest.model_validate_json(
        canonical_json(safe_load_json(root / "evidence-manifest.json"))
    )
    package_result = verify_case_package(root / "case-package")
    package_case = TribunalCase.model_validate_json(
        canonical_json(safe_load_json(root / "case-package/case.json"))
    )
    package_audit = AuditLog.read_jsonl(root / "case-package/audit.jsonl", require_complete=True)
    package_manifest = CasePackageManifest.model_validate_json(
        canonical_json(safe_load_json(root / "case-package/case_package_manifest.json"))
    )
    bundle_values = safe_load_json(root / "case-package/evidence_bundles.json")
    if not isinstance(bundle_values, list):
        raise ValueError("governed demonstration package bundle inventory is malformed")
    package_bundles = tuple(
        EvidenceBundle.model_validate_json(canonical_json(value)) for value in bundle_values
    )
    package_ledger = EvidenceLedgerSnapshot.model_validate_json(
        canonical_json(safe_load_json(root / "case-package/evidence_ledger.json"))
    )
    recomputed = _demonstration_semantic_hash(
        spec_hash=canonical_sha256(spec),
        case=result.case,
        revision=result.case_revision,
        timeline=result.timeline,
        bundle=result.engine_bundle,
        provider_hashes=result.semantic_identities.all_provider_semantic_hashes,
        trusted_execution=result.trusted_execution_identity,
    )
    expected_bindings = (
        (manifest.case_id, result.case.case_id, "outer case identity"),
        (spec.case_id, result.case.case_id, "case specification identity"),
        (evidence_manifest.case_id, result.case.case_id, "evidence manifest identity"),
        (
            manifest.demonstration_semantic_sha256,
            recomputed,
            "demonstration semantic identity",
        ),
        (
            result.semantic_identities.demonstration_semantic_sha256,
            recomputed,
            "result semantic identity",
        ),
        (
            package_result["manifest_hash"],
            manifest.case_package_manifest_hash,
            "case package manifest identity",
        ),
        (
            package_result["export_id"],
            result.export_inventory.export_id,
            "case package export identity",
        ),
        (
            evidence_manifest.outcome,
            result.verdict_eligibility.verdict,
            "evidence manifest verdict",
        ),
        (result.case, package_case, "result-to-package case binding"),
        (result.timeline, package_audit.events, "result-to-package audit binding"),
        (package_bundles, (result.engine_bundle,), "result-to-package bundle binding"),
        (result.evidence, package_ledger.evidence, "result-to-package evidence binding"),
        (result.case_revision, package_result["revision"], "result revision"),
        (
            result.case_revision_identity,
            result.semantic_identities.case_revision_sha256,
            "case revision identity inventory",
        ),
        (
            result.case_revision_identity,
            canonical_sha256(
                {
                    "case_id": result.case.case_id,
                    "case_semantic_sha256": canonical_sha256(result.case),
                    "revision": result.case_revision,
                }
            ),
            "case revision semantic identity",
        ),
        (
            result.export_inventory.manifest_hash,
            package_result["manifest_hash"],
            "result package manifest identity",
        ),
        (
            result.export_inventory.artifact_hashes,
            tuple(sorted(package_manifest.artifacts.items())),
            "result package artifact inventory",
        ),
        (
            result.export_inventory.reconstruction_result,
            package_result,
            "result package reconstruction",
        ),
        (
            evidence_manifest.semantic_identities,
            result.semantic_identities,
            "evidence manifest semantic identities",
        ),
        (
            evidence_manifest.export_inventory,
            result.export_inventory,
            "evidence manifest export inventory",
        ),
        (
            result.semantic_identities.case_spec_sha256,
            canonical_sha256(spec),
            "case specification semantic identity",
        ),
        (
            result.semantic_identities.case_sha256,
            canonical_sha256(result.case),
            "case semantic identity",
        ),
        (
            result.semantic_identities.constitution_sha256,
            _constitution_hash(result.case),
            "constitution semantic identity",
        ),
        (
            result.semantic_identities.amendment_chain_sha256,
            amendment_chain_hash(result.case.amendments),
            "amendment-chain semantic identity",
        ),
        (
            result.semantic_identities.engine_bundle_semantic_sha256,
            result.engine_bundle.semantic_hash,
            "engine-bundle semantic identity",
        ),
        (
            result.semantic_identities.trusted_execution_semantic_sha256,
            _trusted_execution_semantic_hash(result.trusted_execution_identity),
            "trusted execution semantic identity",
        ),
        (
            result.semantic_identities.configuration_semantic_sha256,
            result.trusted_execution_identity.configuration_semantic_sha256,
            "configuration semantic identity",
        ),
        (
            result.semantic_identities.validator_source_sha256,
            result.trusted_execution_identity.validator_source_sha256,
            "validator source identity",
        ),
        (
            result.trusted_execution_identity.case_id,
            result.case.case_id,
            "trusted execution case identity",
        ),
        (
            result.trusted_execution_identity.workflow_revision,
            result.engine_bundle.semantic.workflow_revision,
            "trusted execution revision",
        ),
        (
            result.trusted_execution_identity.constitution_hash,
            _constitution_hash(result.case),
            "trusted execution constitution identity",
        ),
        (
            result.trusted_execution_identity.constitution_id,
            result.engine_bundle.semantic.constitution_id,
            "trusted execution constitution identifier",
        ),
        (
            result.trusted_execution_identity.amendment_chain_hash,
            amendment_chain_hash(result.case.amendments),
            "trusted execution amendment identity",
        ),
        (
            result.trusted_execution_identity.repository,
            result.engine_bundle.semantic.engine.repository,
            "trusted execution repository identity",
        ),
        (
            result.trusted_execution_identity.release,
            result.engine_bundle.semantic.engine.release,
            "trusted execution release identity",
        ),
        (
            result.trusted_execution_identity.annotated_tag_object,
            result.engine_bundle.semantic.engine.annotated_tag_object,
            "trusted execution tag identity",
        ),
        (
            result.trusted_execution_identity.peeled_target,
            result.engine_bundle.semantic.engine.peeled_target,
            "trusted execution peeled target",
        ),
        (
            result.trusted_execution_identity.executable_sha256,
            result.engine_bundle.semantic.engine.executable_sha256,
            "trusted execution executable identity",
        ),
        (
            result.trusted_execution_identity.configuration_sha256,
            result.engine_bundle.semantic.configuration_sha256,
            "trusted execution configuration byte identity",
        ),
        (
            result.trusted_execution_identity.invocation_contract_version,
            result.engine_bundle.semantic.invocation.contract_version,
            "trusted execution invocation contract",
        ),
        (
            result.observational_identities["repository_snapshot_sha256"],
            result.trusted_execution_identity.repository_snapshot_sha256,
            "repository snapshot observation",
        ),
        (
            result.observational_identities["run_fingerprint_sha256"],
            result.trusted_execution_identity.run_fingerprint,
            "run fingerprint observation",
        ),
        (
            result.semantic_identities.verdict_eligibility_sha256,
            canonical_sha256(result.verdict_eligibility),
            "verdict semantic identity",
        ),
        (
            result.semantic_identities.chair_explanation_sha256,
            canonical_sha256(result.case.chair_explanation),
            "Chair semantic identity",
        ),
        (
            result.semantic_identities.all_provider_semantic_hashes,
            tuple(
                record.accepted_result.semantic_hash
                for record in result.role_results
                if record.accepted_result is not None
            ),
            "provider semantic inventory",
        ),
        (
            result.semantic_identities.policy_input_provider_semantic_hashes,
            result.semantic_identities.all_provider_semantic_hashes[:-1],
            "policy-input provider semantic inventory",
        ),
    )
    for observed, required, label in expected_bindings:
        if observed != required:
            raise ValueError(f"governed demonstration has a mismatched {label}")
    if DEMONSTRATION_LABEL not in (root / "tribunal-report.md").read_text(encoding="utf-8"):
        raise ValueError("governed demonstration report lacks its required offline label")
    return {
        "case_id": result.case.case_id,
        "case_package": package_result,
        "demonstration_label": DEMONSTRATION_LABEL,
        "demonstration_semantic_sha256": recomputed,
        "role_results": len(result.role_results),
        "valid": True,
        "verdict": result.verdict_eligibility.verdict.value,
    }


def terminal_summary(result: GovernedTribunalResult) -> str:
    facts = _fact_values(result)
    review = result.case.statistical_review
    adversarial = result.case.adversarial_review
    reproducibility = result.case.reproducibility_review
    if review is None or adversarial is None or reproducibility is None:
        raise ValueError("terminal summary requires every reviewer output")
    return "\n".join(
        (
            DEMONSTRATION_LABEL,
            f"Claim: {result.case.claim.statement}",
            (
                "Major objections: corrected p-value "
                f"{canonical_decimal(facts['fact_reality_check_p_value'])}; maximum drawdown "
                f"{_percent(facts['fact_max_drawdown'])}; bootstrap loss probability "
                f"{_percent(facts['fact_probability_loss'])}."
            ),
            (
                "Engine evidence: total return "
                f"{_percent(facts['fact_portfolio_total_return'])}; benchmark return "
                f"{_percent(facts['fact_benchmark_total_return'])}; excess return "
                f"{_percent(facts['fact_excess_return'])}; costs "
                f"{_currency(facts['fact_total_transaction_costs'])}."
            ),
            (
                f"Reviewer findings: inference={review.corrected_inference.value}; "
                f"robustness={adversarial.robustness_status.value}; "
                f"reproducibility={reproducibility.status.value}."
            ),
            f"Deterministic verdict: {result.verdict_eligibility.verdict.value}.",
            "Reconstruction: exact durable export replay verified; duplicate transitions: 0.",
            (
                "Limitations: synthetic evidence, deterministic mock roles, no live provider, no "
                "trading, no financial advice."
            ),
        )
    )


def _create_claim(store: SQLiteCaseStore, spec: DemoCaseSpecification) -> None:
    claim = ResearchClaim(
        claim_id=CLAIM_ID,
        statement=spec.claim,
        submitted_by=f"{DEMONSTRATION_LABEL} operator",
        submitted_at=_time(0),
        scope=ClaimScope(
            asset_classes=("deterministic_synthetic",),
            universe=("SYN_BENCH", "SYN_CRYPTO", "SYN_EQ_A", "SYN_EQ_B", "SYN_EQ_C"),
            start_date="2019-01-01",
            end_date="2025-12-31",
        ),
    )
    case = TribunalCase(case_id=CASE_ID, state=WorkflowState.CLAIM_RECEIVED, claim=claim)
    audit = AuditLog()
    audit.append(
        timestamp=claim.submitted_at,
        case_id=CASE_ID,
        workflow_state=WorkflowState.CLAIM_RECEIVED,
        actor=RoleName.SYSTEM,
        action="receive_claim",
        payload=claim,
    )
    store.create_case(case, audit.events[0])


def _invoke_with_replay_probe(
    orchestrator: TribunalOrchestrator,
    store: SQLiteCaseStore,
    action: RoleAction,
    effective_at: datetime,
    replayed_actions: list[RoleAction],
    *,
    evidence_summaries: tuple[EvidenceSummary, ...] = (),
    code_owned_reproducibility_verified: bool = False,
    final_claim_graph: ClaimGraph | None = None,
) -> None:
    before = store.reconstruct(CASE_ID, require_complete=False).revision
    accepted = orchestrator.invoke_and_advance(
        store,
        case_id=CASE_ID,
        action=action,
        effective_at=effective_at,
        evidence_summaries=evidence_summaries,
        code_owned_reproducibility_verified=code_owned_reproducibility_verified,
        final_claim_graph=final_claim_graph,
    )
    after = store.reconstruct(CASE_ID, require_complete=False).revision
    replayed = orchestrator.invoke_and_advance(
        store,
        case_id=CASE_ID,
        action=action,
        effective_at=effective_at,
        evidence_summaries=evidence_summaries,
        code_owned_reproducibility_verified=code_owned_reproducibility_verified,
        final_claim_graph=final_claim_graph,
    )
    final_revision = store.reconstruct(CASE_ID, require_complete=False).revision
    if accepted != replayed or after != before + 1 or final_revision != after:
        raise ValueError("provider replay created a duplicate or divergent transition")
    replayed_actions.append(action)


def _approve_and_lock(store: SQLiteCaseStore) -> None:
    durable = store.reconstruct(CASE_ID, require_complete=False)
    proposal = durable.case.proposal
    if proposal is None:
        raise ValueError("simulated human approval requires the governed proposal")
    approval = create_human_approval(
        approval_id="approval_governed_tribunal",
        proposal=proposal,
        approver="explicit simulated human approver for the offline demonstration",
        approved_at=_time(3),
    )
    machine = StateMachine(durable.case, durable.audit_log)
    machine.advance(
        WorkflowState.HUMAN_APPROVAL,
        actor=RoleName.HUMAN_APPROVER,
        action="record_approval",
        timestamp=_time(4),
        payload=approval,
        updates={"human_approval": approval},
    )
    store.append_event(machine.audit_log.events[-1], expected_revision=durable.revision)
    approved = store.reconstruct(CASE_ID, require_complete=False)
    constitution = lock_constitution(
        constitution_id="constitution_governed_tribunal",
        proposal=proposal,
        approval=approval,
        locked_at=_time(5),
    )
    machine = StateMachine(approved.case, approved.audit_log)
    machine.advance(
        WorkflowState.CONSTITUTION_LOCKED,
        actor=RoleName.SYSTEM,
        action="lock_constitution",
        timestamp=_time(6),
        payload=constitution,
        updates={"constitution": constitution},
    )
    store.append_event(machine.audit_log.events[-1], expected_revision=approved.revision)


def _enter_follow_up(store: SQLiteCaseStore) -> None:
    durable = store.reconstruct(CASE_ID, require_complete=False)
    machine = StateMachine(durable.case, durable.audit_log)
    machine.advance(
        WorkflowState.OPTIONAL_FOLLOW_UP,
        actor=RoleName.SYSTEM,
        action="enter_follow_up",
        timestamp=_time(10),
        payload={"follow_up_required": False},
    )
    store.append_event(machine.audit_log.events[-1], expected_revision=durable.revision)


def _compute_verdict(
    store: SQLiteCaseStore,
    provider_semantic_hashes: tuple[str, ...],
) -> VerdictEligibility:
    durable = store.reconstruct(CASE_ID, require_complete=False)
    case = durable.case
    if (
        case.proposal is None
        or case.methodology_review is None
        or case.statistical_review is None
        or case.adversarial_review is None
        or case.reproducibility_review is None
        or durable.evidence_ledger is None
    ):
        raise ValueError("verdict computation requires the complete governed review record")
    evidence = durable.evidence_ledger.snapshot().evidence
    decisive = tuple(
        EvidenceReference(
            evidence_id=item.evidence_id,
            numeric_fact_ids=tuple(fact.fact_id for fact in item.numeric_facts),
        )
        for item in evidence
    )
    findings = (
        *case.methodology_review.findings,
        *case.statistical_review.findings,
        *case.adversarial_review.findings,
        *case.reproducibility_review.findings,
    )
    inputs = VerdictInputs(
        methodology_status=case.methodology_review.decision,
        primary_experiment_complete=True,
        evidence_validation_statuses=tuple(item.validation_status for item in evidence),
        corrected_inference=case.statistical_review.corrected_inference,
        expected_direction=case.proposal.primary_hypothesis.expected_direction,
        effect_direction=case.statistical_review.effect_direction,
        practical_significance=case.statistical_review.practical_significance,
        robustness_status=case.adversarial_review.robustness_status,
        cost_sensitivity=case.adversarial_review.cost_sensitivity,
        parameter_stability=case.adversarial_review.parameter_stability,
        regime_stability=case.adversarial_review.regime_stability,
        concentration_risk=case.adversarial_review.concentration_risk,
        reproducibility_status=case.reproducibility_review.status,
        unresolved_critical_findings=any(
            finding.severity is FindingSeverity.CRITICAL and not finding.resolved
            for finding in findings
        ),
        contradictory_evidence=(),
        unresolved_noncritical_limitations=any(
            finding.severity is FindingSeverity.NONCRITICAL and not finding.resolved
            for finding in findings
        ),
        decisive_evidence=decisive,
        provider_semantic_hashes=provider_semantic_hashes,
    )
    eligibility = VerdictPolicy.compute(
        inputs,
        eligibility_id=f"eligibility_{canonical_sha256(inputs)[:24]}",
        computed_at=_time(12),
    )
    machine = StateMachine(case, durable.audit_log)
    machine.advance(
        WorkflowState.VERDICT_ELIGIBILITY_COMPUTED,
        actor=RoleName.SYSTEM,
        action="compute_verdict",
        timestamp=_time(12),
        payload={"inputs": inputs, "eligibility": eligibility},
        updates={"verdict_eligibility": eligibility},
    )
    store.append_event(machine.audit_log.events[-1], expected_revision=durable.revision)
    return eligibility


def _build_graph(store: SQLiteCaseStore) -> ClaimGraph:
    durable = store.reconstruct(CASE_ID, require_complete=False)
    if durable.evidence_ledger is None:
        raise ValueError("final claim graph requires admitted evidence")
    graph = ClaimGraph()
    graph.add_node(
        GraphNode(
            node_id=durable.case.claim.claim_id,
            node_type=NodeType.CLAIM,
            substantive_final_claim=True,
        )
    )
    for index, evidence in enumerate(durable.evidence_ledger.snapshot().evidence, start=1):
        graph.add_node(
            GraphNode(
                node_id=evidence.evidence_id,
                node_type=NodeType.EVIDENCE,
                evidence_sha256=evidence.content_sha256,
                evidence_validation_status=evidence.validation_status,
            )
        )
        graph.add_edge(
            GraphEdge(
                edge_id=f"edge_{index:03d}_{CASE_ID}",
                source_id=evidence.evidence_id,
                target_id=durable.case.claim.claim_id,
                edge_type=EdgeType(EvidenceRelationship.SUPPORTS.value),
            )
        )
    graph.validate_against_ledger(durable.evidence_ledger)
    graph.validate_final_claim_traceability()
    return graph


def _evidence_summaries(
    evidence_items: tuple[EvidenceObject, ...],
    case: TribunalCase,
    revision: int,
) -> tuple[EvidenceSummary, ...]:
    if case.constitution is None:
        raise ValueError("evidence summary requires the immutable constitution")
    return tuple(
        EvidenceSummary(
            case_id=case.case_id,
            case_revision=revision,
            constitution_identity=case.constitution.constitution_hash,
            amendment_chain_identity=amendment_chain_hash(case.amendments),
            evidence_id=evidence.evidence_id,
            numeric_fact_ids=tuple(fact.fact_id for fact in evidence.numeric_facts),
            summary=(
                "Validated C++ v1.0.0 evidence facts: "
                + ", ".join(
                    f"{fact.fact_id}={canonical_decimal(fact.value)} {fact.unit}"
                    for fact in evidence.numeric_facts
                )
            ),
        )
        for evidence in evidence_items
    )


def _revision_summaries(
    store: SQLiteCaseStore,
    evidence_items: tuple[EvidenceObject, ...],
    revision: int,
) -> tuple[EvidenceSummary, ...]:
    durable = store.reconstruct(CASE_ID, require_complete=False)
    if durable.revision != revision:
        raise ValueError("evidence summary revision differs from durable state")
    return _evidence_summaries(evidence_items, durable.case, revision)


def _demonstration_semantic_hash(
    *,
    spec_hash: str,
    case: TribunalCase,
    revision: int,
    timeline: tuple[AuditEvent, ...],
    bundle: EvidenceBundle,
    provider_hashes: tuple[str, ...],
    trusted_execution: DemoTrustedExecutionIdentity,
) -> str:
    return canonical_sha256(
        {
            "amendment_chain_sha256": amendment_chain_hash(case.amendments),
            "case": case,
            "case_spec_sha256": spec_hash,
            "constitution_sha256": _constitution_hash(case),
            "engine": bundle.semantic.engine,
            "engine_bundle_semantic_sha256": bundle.semantic_hash,
            "numeric_facts": bundle.semantic.numeric_facts,
            "provider_semantic_hashes": provider_hashes,
            "revision": revision,
            "trusted_execution_semantic_sha256": _trusted_execution_semantic_hash(
                trusted_execution
            ),
            "timeline": tuple(
                {
                    "action": event.action,
                    "actor": event.actor,
                    "sequence": event.sequence,
                    "workflow_state": event.workflow_state,
                }
                for event in timeline
            ),
        }
    )


def _trusted_execution_identity(
    record: TrustedReceiptRecord,
) -> DemoTrustedExecutionIdentity:
    if record.adapter_contract_version != "cpp-v1-adapter/2.0":
        raise ValueError("trusted execution adapter contract is not approved")
    return DemoTrustedExecutionIdentity(
        adapter_contract_version="cpp-v1-adapter/2.0",
        case_id=record.case_id,
        workflow_revision=record.workflow_revision,
        constitution_id=record.constitution_id,
        constitution_hash=record.constitution_hash,
        amendment_chain_hash=record.amendment_chain_hash,
        repository=record.repository,
        release=record.release,
        annotated_tag_object=record.annotated_tag_object,
        peeled_target=record.peeled_target,
        executable_sha256=record.executable_sha256,
        configuration_sha256=record.configuration_sha256,
        configuration_semantic_sha256=record.configuration_semantic_sha256,
        invocation_contract_version=record.invocation_contract_version,
        repository_snapshot_sha256=record.repository_snapshot_sha256,
        validator_source_sha256=record.validator_source_sha256,
        run_fingerprint=record.run_fingerprint,
    )


def _trusted_execution_semantic_hash(identity: DemoTrustedExecutionIdentity) -> str:
    return canonical_sha256(
        identity.model_dump(
            mode="python",
            exclude={"repository_snapshot_sha256", "run_fingerprint"},
        )
    )


def _evidence_manifest(
    spec: DemoCaseSpecification,
    result: GovernedTribunalResult,
) -> DemoEvidenceManifest:
    facts = _fact_values(result)
    definitions = (
        ("fact_portfolio_total_return", "Headline total return", "Attractive point estimate"),
        ("fact_benchmark_total_return", "SYN_BENCH return", "Parity benchmark"),
        ("fact_excess_return", "Excess return", "Economically large point estimate"),
        ("fact_total_transaction_costs", "Transaction costs", "Explicitly included"),
        ("fact_max_drawdown", "Maximum drawdown", "Fails the preregistered limit"),
        ("fact_reality_check_p_value", "Corrected p-value", "Fails the 0.05 criterion"),
        ("fact_return_lower_95", "95 percent return lower bound", "Crosses zero"),
        ("fact_probability_loss", "Bootstrap loss probability", "Fails the 10 percent limit"),
        ("fact_crypto_profit_share", "SYN_CRYPTO profit share", "Concentration objection"),
    )
    units = {fact.fact_id: fact.unit for fact in result.engine_bundle.semantic.numeric_facts}
    return DemoEvidenceManifest(
        demonstration_label=DEMONSTRATION_LABEL,
        case_id=result.case.case_id,
        claim=spec.claim,
        outcome=result.verdict_eligibility.verdict,
        lifecycle=tuple(event.workflow_state.value for event in result.timeline),
        key_evidence=tuple(
            EvidenceHighlight(
                fact_id=fact_id,
                label=label,
                value=facts[fact_id],
                unit=units[fact_id],
                interpretation=interpretation,
            )
            for fact_id, label, interpretation in definitions
        ),
        semantic_identities=result.semantic_identities,
        export_inventory=result.export_inventory,
        presentation_cautions=(
            "Do not describe mock wording as proof of model intelligence.",
            "Do not describe synthetic output as real or expected profitability.",
            "Show that code computes the verdict before the Chair is called.",
            "Keep the offline mock label visible in every capture.",
        ),
        suggested_capture_order=(
            "case-spec.json claim and failure criteria",
            "tribunal-result.json role provenance and engine identities",
            "tribunal-report.md evidence table and INCONCLUSIVE verdict",
            "demo verify terminal output proving independent reconstruction",
        ),
    )


def _render_report(spec: DemoCaseSpecification, result: GovernedTribunalResult) -> str:
    facts = _fact_values(result)
    case = result.case
    methodology = case.methodology_review
    statistics = case.statistical_review
    adversarial = case.adversarial_review
    reproducibility = case.reproducibility_review
    chair = case.chair_explanation
    constitution = case.constitution
    if None in (methodology, statistics, adversarial, reproducibility, chair, constitution):
        raise ValueError("human report requires a complete governed case")
    assert methodology is not None
    assert statistics is not None
    assert adversarial is not None
    assert reproducibility is not None
    assert chair is not None
    assert constitution is not None
    evidence_rows = (
        ("Portfolio total return", _percent(facts["fact_portfolio_total_return"]), "Attractive"),
        ("SYN_BENCH total return", _percent(facts["fact_benchmark_total_return"]), "Control"),
        ("Excess return", _percent(facts["fact_excess_return"]), "Attractive"),
        ("Transaction costs", _currency(facts["fact_total_transaction_costs"]), "Included"),
        ("Maximum drawdown", _percent(facts["fact_max_drawdown"]), "Fails -30% limit"),
        (
            "Corrected reality-check p-value",
            canonical_decimal(facts["fact_reality_check_p_value"]),
            "Fails <0.05",
        ),
        (
            "95% return interval",
            (
                f"{_percent(facts['fact_return_lower_95'])} to "
                f"{_percent(facts['fact_return_upper_95'])}"
            ),
            "Crosses zero",
        ),
        ("Bootstrap loss probability", _percent(facts["fact_probability_loss"]), "Fails ≤10%"),
        (
            "SYN_CRYPTO share of net profit",
            _percent(facts["fact_crypto_profit_share"]),
            "Concentration",
        ),
    )
    rows = "\n".join(f"| {name} | {value} | {reading} |" for name, value, reading in evidence_rows)
    evidence_inventory_lines: list[str] = []
    for evidence in result.evidence:
        count = len(evidence.numeric_facts)
        noun = "fact" if count == 1 else "facts"
        evidence_inventory_lines.append(
            f"- Evidence `{evidence.evidence_id}`: `{evidence.source_artifact}` "
            f"({count} admitted numeric {noun})."
        )
    evidence_inventory = "\n".join(evidence_inventory_lines)
    methodology_findings = "\n".join(
        f"- {finding.summary} ({'resolved' if finding.resolved else 'retained limitation'})"
        for finding in methodology.findings
    )
    role_findings = "\n".join(
        (
            (
                "- Researcher: preregistered benchmark, costs, corrected inference, drawdown, "
                "and failure gates."
            ),
            (
                f"- Methodology Auditor: {methodology.decision.value}; headline return alone is "
                "insufficient."
            ),
            (
                "- Statistical Reviewer: corrected inference "
                f"`{statistics.corrected_inference.value}`; reliability unsupported."
            ),
            (
                f"- Adversarial Reviewer: robustness `{adversarial.robustness_status.value}` with "
                "drawdown, loss, regime, and concentration objections."
            ),
            (
                f"- Reproducibility Reviewer: `{reproducibility.status.value}` after code-owned "
                "reconstruction."
            ),
            (
                f"- Tribunal Chair: explains `{chair.computed_verdict.value}` without selecting "
                "or upgrading it."
            ),
        )
    )
    return "\n".join(
        (
            f"# {DEMONSTRATION_LABEL}",
            "",
            "## Governed research tribunal report",
            "",
            (
                "Financial and quantitative AI can produce persuasive strategy narratives without "
                "proving that the experiment, inputs, execution, statistics, evidence, or "
                "reasoning "
                "are trustworthy and reproducible. This case shows the QuantForge distinction "
                "through preregistration, independent role authority, trusted numerical execution, "
                "adversarial review, evidence lineage, and deterministic verdict authority."
            ),
            "",
            "## Original falsifiable claim",
            "",
            spec.claim,
            "",
            (
                "The claim is research-only. It does not concern live trading, financial advice, "
                "or future returns."
            ),
            "",
            "## Constitution and human approval",
            "",
            "- Simulated human approval: explicit and recorded before numerical execution.",
            f"- Constitution identity: `{constitution.constitution_hash}`.",
            (
                "- Amendment-chain identity: "
                f"`{amendment_chain_hash(case.amendments)}` (no amendments)."
            ),
            (
                "- Strategy/configuration: frozen C++ `portfolio_equal_weight.json`, causal "
                "MA-cross signals, monthly equal-weight allocation, 40% maximum weight, and a "
                "2% cash buffer."
            ),
            (
                "- Costs: 10 bps commission plus 5 bps slippage per fill on 100,000 USD starting "
                "capital."
            ),
            (
                "- Statistical acceptance: corrected p-value below 0.05, return interval above "
                "zero, positive-active probability at least 95%, and loss probability at most 10%."
            ),
            "",
            "Methodology objections were incorporated as decisive constitution criteria:",
            "",
            methodology_findings,
            "",
            "## Trusted C++ evidence",
            "",
            (
                "The C++ `v1.0.0` adapter executed the approved public synthetic fixture through "
                "the trusted execute-and-admit path. QuantForge independently checked the "
                "protected "
                "repository, annotated tag, peeled target, executable digest, configuration, six "
                "inputs, validator, output inventory, and admitted fact locations."
            ),
            "",
            f"- Engine repository: `{result.engine_bundle.semantic.engine.repository}`.",
            (
                f"- Release/tag: `{result.engine_bundle.semantic.engine.release}` / "
                f"`{result.engine_bundle.semantic.engine.annotated_tag_object}`."
            ),
            f"- Peeled target: `{result.engine_bundle.semantic.engine.peeled_target}`.",
            (f"- Executable SHA-256: `{result.engine_bundle.semantic.engine.executable_sha256}`."),
            (f"- Configuration SHA-256: `{result.engine_bundle.semantic.configuration_sha256}`."),
            (
                "- Configuration semantic SHA-256: "
                f"`{result.trusted_execution_identity.configuration_semantic_sha256}`."
            ),
            (
                "- Validator source SHA-256: "
                f"`{result.trusted_execution_identity.validator_source_sha256}`."
            ),
            (
                "- Repository snapshot SHA-256 (host observation): "
                f"`{result.trusted_execution_identity.repository_snapshot_sha256}`."
            ),
            (
                "- Trusted adapter contract: "
                f"`{result.trusted_execution_identity.adapter_contract_version}`."
            ),
            f"- Bundle semantic SHA-256: `{result.engine_bundle.semantic_hash}`.",
            (
                f"- Evidence ledger: `{len(result.evidence)}` source-bound objects with "
                f"`{len(result.engine_bundle.semantic.numeric_facts)}` admitted numeric facts."
            ),
            evidence_inventory,
            (
                f"- Output inventory: `{len(result.engine_bundle.semantic.output_artifacts)}` "
                "validated artifacts; validator status "
                f"`{result.engine_bundle.semantic.validator_results[0].status}`."
            ),
            "",
            "| Evidence | Value | Tribunal reading |",
            "|---|---:|---|",
            rows,
            "",
            (
                "The point estimate is attractive. The reliability claim is not supported: "
                "corrected inference fails, the confidence interval includes a substantial loss, "
                "drawdown breaches the constitution, and loss/concentration/regime objections "
                "remain."
            ),
            "",
            "## Differentiated role findings",
            "",
            role_findings,
            "",
            (
                "Every statistical and adversarial finding cites admitted evidence IDs and their "
                "allow-listed numeric fact IDs. Provider output cannot add evidence, execute the "
                "engine, record approval, advance workflow state, or compute eligibility."
            ),
            "",
            "## Deterministic verdict",
            "",
            (
                f"**{result.verdict_eligibility.verdict.value}** — "
                f"{result.verdict_eligibility.decisive_reasons[0]}."
            ),
            "",
            (
                "The verdict was computed by `VerdictPolicy 1.0` before the Chair request. The "
                f"Chair summary is: “{chair.summary}”. Its wording cannot alter the stored "
                "eligibility "
                "or decisive evidence set."
            ),
            "",
            "## Replay, reconstruction, and export",
            "",
            (
                f"- Final revision: `{result.case_revision}` with `{len(result.timeline)}` "
                "hash-linked events."
            ),
            (
                "- Six accepted role transactions and six immediate replay probes produced zero "
                "duplicate transitions."
            ),
            f"- Durable export ID: `{result.export_inventory.export_id}`.",
            (f"- Case-package manifest identity: `{result.export_inventory.manifest_hash}`."),
            "- Independent package reconstruction: verified.",
            (
                "- Stable demonstration semantic identity: "
                f"`{result.semantic_identities.demonstration_semantic_sha256}`."
            ),
            "",
            (
                "Trusted execution timestamps and raw JSON byte observations may vary. They are "
                "explicitly separated from stable semantic identities, retained in observational "
                "provenance, and transitively protected by bundle, audit, graph, and export hashes."
            ),
            "",
            "## What is real and what is mock",
            "",
            (
                "Real: lifecycle state transitions, role-specific request construction, "
                "schema/prompt/policy identities, validation, SQLite persistence, explicit "
                "simulated human approval, immutable constitution, genuine C++ execution, evidence "
                "admission, deterministic verdict policy, export, replay, and reconstruction."
            ),
            "",
            (
                "Deterministic mock output: the six advisory role narratives. They pass through "
                "the same governed provider contracts and provenance boundary used by the live "
                "provider "
                "surface, but they do not demonstrate model intelligence."
            ),
            "",
            (
                "Pending: separately authorized live OpenAI verification. This demonstration "
                "performs no OpenAI, ZenMux, Claude, Kimi, or other external model call and "
                "requires "
                "no API credential."
            ),
            "",
            "## Limitations and next actions",
            "",
            (
                "- Synthetic evidence does not establish real profitability, live-market "
                "performance, or future returns."
            ),
            (
                "- This is not financial advice, trading, paper trading, order placement, or "
                "strategy deployment."
            ),
            (
                "- The verdict remains INCONCLUSIVE unless new trusted evidence changes code-owned "
                "policy inputs."
            ),
            (
                "- Local hash chains detect partial tampering but are not externally signed or "
                "anchored."
            ),
            "",
        )
    )


def _artifact_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _fact_values(result: GovernedTribunalResult) -> dict[str, Decimal]:
    return {fact.fact_id: fact.value for fact in result.engine_bundle.semantic.numeric_facts}


def _constitution_hash(case: TribunalCase) -> str:
    if case.constitution is None:
        raise ValueError("governed demonstration requires its constitution")
    return case.constitution.constitution_hash


def _time(offset: int) -> datetime:
    return _TIMELINE_START + timedelta(hours=offset)


def _percent(value: Decimal) -> str:
    return f"{(value * Decimal('100')).quantize(Decimal('0.01'))}%"


def _currency(value: Decimal) -> str:
    return f"${value.quantize(Decimal('0.01')):,.2f}"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "DEMONSTRATION_LABEL",
    "DemoArtifactManifest",
    "DemoCaseSpecification",
    "DemoEvidenceManifest",
    "GovernedTribunalResult",
    "case_specification",
    "run_governed_tribunal_demo",
    "terminal_summary",
    "verify_governed_tribunal_demo",
]
