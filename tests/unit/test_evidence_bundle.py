from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from quantforge.evidence.bundle import (
    GENESIS_BUNDLE_HASH,
    ArtifactObservation,
    ArtifactSemanticIdentity,
    EngineIdentity,
    EvidenceAdmissionContext,
    EvidenceBundle,
    EvidenceBundleObservations,
    EvidenceBundleSemantic,
    HmacSha256TestSigner,
    InvocationIdentity,
    NumericFactReference,
    ValidatorResult,
    _read_bounded_csv,
    artifact_semantic_sha256,
    evidence_from_bundle,
    verify_evidence_bundle,
)
from quantforge.serialization.canonical import canonical_json, canonical_sha256


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle_fixture(
    tmp_path: Path,
    *,
    signer: HmacSha256TestSigner | None = None,
    timestamp: str = "2026-01-01T00:00:00Z",
) -> tuple[EvidenceBundle, EvidenceAdmissionContext, Path]:
    root = tmp_path / "outputs"
    root.mkdir(parents=True)
    (root / "summary.csv").write_text("schema_version,total_return\n3,0.125\n", encoding="utf-8")
    (root / "metadata.json").write_text(
        f'{{"result_schema_version":2,"run_timestamp_utc":"{timestamp}"}}\n',
        encoding="utf-8",
    )
    output_semantics = tuple(
        sorted(
            (
                ArtifactSemanticIdentity(
                    path="metadata.json",
                    semantic_sha256=artifact_semantic_sha256(root / "metadata.json"),
                    schema_version="2",
                ),
                ArtifactSemanticIdentity(
                    path="summary.csv",
                    semantic_sha256=artifact_semantic_sha256(root / "summary.csv"),
                    schema_version="3",
                ),
            ),
            key=lambda item: item.path,
        )
    )
    output_observations = tuple(
        sorted(
            (
                ArtifactObservation(
                    path="metadata.json",
                    byte_sha256=_file_sha(root / "metadata.json"),
                    size_bytes=(root / "metadata.json").stat().st_size,
                ),
                ArtifactObservation(
                    path="summary.csv",
                    byte_sha256=_file_sha(root / "summary.csv"),
                    size_bytes=(root / "summary.csv").stat().st_size,
                ),
            ),
            key=lambda item: item.path,
        )
    )
    input_semantics = (
        ArtifactSemanticIdentity(
            path="data/input.csv",
            semantic_sha256="1" * 64,
            schema_version="csv-v1",
        ),
    )
    input_observations = (
        ArtifactObservation(path="data/input.csv", byte_sha256="1" * 64, size_bytes=10),
    )
    start = datetime(2026, 1, 1, tzinfo=UTC)
    observations = EvidenceBundleObservations(
        execution_started_at=start,
        execution_completed_at=start + timedelta(seconds=1),
        admitted_at=start + timedelta(seconds=2),
        input_artifacts=input_observations,
        output_artifacts=output_observations,
        stdout_sha256="2" * 64,
        stderr_sha256="3" * 64,
    )
    semantic = EvidenceBundleSemantic(
        bundle_id="bundle_test",
        case_id="case_test",
        workflow_revision=5,
        constitution_id="constitution_test",
        constitution_hash="4" * 64,
        amendment_chain_hash="5" * 64,
        engine=EngineIdentity(executable_sha256="6" * 64),
        invocation=InvocationIdentity(),
        configuration_sha256="7" * 64,
        input_artifacts=input_semantics,
        output_artifacts=output_semantics,
        validator_results=(
            ValidatorResult(name="validate_results", status="passed", output_sha256="8" * 64),
        ),
        numeric_facts=(
            NumericFactReference(
                fact_id="fact_return",
                name="portfolio return",
                artifact_path="summary.csv",
                structured_location="/rows/0/total_return",
                value=Decimal("0.125"),
                unit="fraction",
                methodology_id="causal_daily_v3_stochastic_v2",
            ),
        ),
        previous_bundle_hash=GENESIS_BUNDLE_HASH,
    )
    bundle = EvidenceBundle.create(semantic, observations, signer=signer)
    context = EvidenceAdmissionContext(
        case_id="case_test",
        workflow_revision=5,
        constitution_id="constitution_test",
        constitution_hash="4" * 64,
        amendment_chain_hash="5" * 64,
        engine=semantic.engine,
        configuration_sha256="7" * 64,
        input_artifacts=input_semantics,
        input_artifact_observations=input_observations,
        now=start + timedelta(seconds=2),
    )
    return bundle, context, root


def test_json_volatile_exclusions_are_root_path_specific(tmp_path: Path) -> None:
    artifact = tmp_path / "metadata.json"
    artifact.write_text(
        '{"run_timestamp_utc":"first","nested":{"timestamp":"semantic-first"}}\n',
        encoding="utf-8",
    )
    first = artifact_semantic_sha256(artifact)
    artifact.write_text(
        '{"run_timestamp_utc":"second","nested":{"timestamp":"semantic-first"}}\n',
        encoding="utf-8",
    )
    assert artifact_semantic_sha256(artifact) == first
    artifact.write_text(
        '{"run_timestamp_utc":"second","nested":{"timestamp":"semantic-second"}}\n',
        encoding="utf-8",
    )
    assert artifact_semantic_sha256(artifact) != first


def test_bundle_verifies_and_converts_without_reinterpreting_numeric_fact(
    tmp_path: Path,
) -> None:
    bundle, context, root = _bundle_fixture(tmp_path)
    verify_evidence_bundle(bundle, context, root)
    evidence = evidence_from_bundle(
        bundle,
        evidence_id="evidence_test",
        claim_id="claim_test",
        experiment_id="experiment_test",
    )
    assert evidence.numeric_facts[0].value == Decimal("0.125")
    assert evidence.source_artifact_sha256 == _file_sha(root / "summary.csv")
    assert evidence.provenance["bundle_hash"] == bundle.bundle_hash
    assert evidence.validation_method == "cpp_v1_release_validators"


def test_hashes_bind_semantics_observations_and_signature(tmp_path: Path) -> None:
    signer = HmacSha256TestSigner(
        signer_id="signer_test", secret=b"0123456789abcdef0123456789abcdef"
    )
    bundle, context, root = _bundle_fixture(tmp_path, signer=signer)
    assert bundle.semantic_hash == canonical_sha256(bundle.semantic)
    assert bundle.observation_hash == canonical_sha256(bundle.observations)
    assert bundle.bundle_hash == canonical_sha256(
        {
            "observation_hash": bundle.observation_hash,
            "semantic_hash": bundle.semantic_hash,
        }
    )
    verify_evidence_bundle(bundle, context, root, signer=signer)
    wrong = HmacSha256TestSigner(
        signer_id="signer_test", secret=b"fedcba9876543210fedcba9876543210"
    )
    with pytest.raises(ValueError, match="signature"):
        verify_evidence_bundle(bundle, context, root, signer=wrong)
    with pytest.raises(ValueError, match="signature verifier"):
        verify_evidence_bundle(bundle, context, root)


def test_repeated_semantics_are_byte_identical_with_observations_separated(
    tmp_path: Path,
) -> None:
    first, _, _ = _bundle_fixture(tmp_path / "first", timestamp="2026-01-01T00:00:00Z")
    second, _, _ = _bundle_fixture(tmp_path / "second", timestamp="2026-01-02T00:00:00Z")
    assert canonical_json(first.semantic) == canonical_json(second.semantic)
    assert first.semantic_hash == second.semantic_hash
    assert first.observation_hash != second.observation_hash
    assert first.bundle_hash != second.bundle_hash


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("case_id", "case_other", "case"),
        ("workflow_revision", 4, "workflow revision"),
        ("constitution_id", "constitution_other", "constitution identifier"),
        ("constitution_hash", "9" * 64, "constitution hash"),
        ("amendment_chain_hash", "9" * 64, "amendment chain"),
        ("configuration_sha256", "9" * 64, "configuration"),
        ("previous_bundle_hash", "9" * 64, "bundle-chain parent"),
    ],
)
def test_cross_case_stale_and_substitution_contexts_are_rejected(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    bundle, context, root = _bundle_fixture(tmp_path)
    changed = context.model_copy(update={field: value})
    with pytest.raises(ValueError, match=message):
        verify_evidence_bundle(bundle, changed, root)


def test_executable_and_input_substitution_are_rejected(tmp_path: Path) -> None:
    bundle, context, root = _bundle_fixture(tmp_path)
    changed_engine = context.model_copy(
        update={"engine": EngineIdentity(executable_sha256="f" * 64)}
    )
    with pytest.raises(ValueError, match="engine identity"):
        verify_evidence_bundle(bundle, changed_engine, root)
    changed_input = context.model_copy(
        update={
            "input_artifact_observations": (
                ArtifactObservation(path="data/input.csv", byte_sha256="f" * 64, size_bytes=10),
            )
        }
    )
    with pytest.raises(ValueError, match="observed input"):
        verify_evidence_bundle(bundle, changed_input, root)


def test_missing_extra_changed_and_symlink_outputs_are_rejected(tmp_path: Path) -> None:
    bundle, context, root = _bundle_fixture(tmp_path / "missing")
    (root / "summary.csv").unlink()
    with pytest.raises(ValueError, match="inventory mismatch"):
        verify_evidence_bundle(bundle, context, root)

    bundle, context, root = _bundle_fixture(tmp_path / "extra")
    (root / "extra.csv").write_text("value\n1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="inventory mismatch"):
        verify_evidence_bundle(bundle, context, root)

    bundle, context, root = _bundle_fixture(tmp_path / "changed")
    (root / "summary.csv").write_text("schema_version,total_return\n3,0.250\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"size mismatch|hash mismatch"):
        verify_evidence_bundle(bundle, context, root)

    bundle, context, root = _bundle_fixture(tmp_path / "symlink")
    target = root / "target"
    target.write_text("x", encoding="utf-8")
    (root / "link").symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        verify_evidence_bundle(bundle, context, root)


def test_forged_numeric_reference_and_nonfinite_csv_are_rejected(tmp_path: Path) -> None:
    bundle, context, root = _bundle_fixture(tmp_path / "forged")
    forged_fact = bundle.semantic.numeric_facts[0].model_copy(update={"value": Decimal("0.5")})
    forged_semantic = bundle.semantic.model_copy(update={"numeric_facts": (forged_fact,)})
    forged = EvidenceBundle.create(forged_semantic, bundle.observations)
    with pytest.raises(ValueError, match="does not match"):
        verify_evidence_bundle(forged, context, root)

    bundle, context, root = _bundle_fixture(tmp_path / "nan")
    (root / "summary.csv").write_text("schema_version,total_return\n3,NaN\n", encoding="utf-8")
    observation = ArtifactObservation(
        path="summary.csv",
        byte_sha256=_file_sha(root / "summary.csv"),
        size_bytes=(root / "summary.csv").stat().st_size,
    )
    observations = bundle.observations.model_copy(
        update={
            "output_artifacts": tuple(
                observation if item.path == "summary.csv" else item
                for item in bundle.observations.output_artifacts
            )
        }
    )
    semantic_item = ArtifactSemanticIdentity(
        path="summary.csv",
        semantic_sha256=artifact_semantic_sha256(root / "summary.csv"),
        schema_version="3",
    )
    semantic = bundle.semantic.model_copy(
        update={
            "output_artifacts": tuple(
                semantic_item if item.path == "summary.csv" else item
                for item in bundle.semantic.output_artifacts
            )
        }
    )
    nonfinite = EvidenceBundle.create(semantic, observations)
    with pytest.raises(ValueError, match="non-finite"):
        verify_evidence_bundle(nonfinite, context, root)


def test_future_timestamps_finalization_and_signing_policy_are_rejected(tmp_path: Path) -> None:
    bundle, context, root = _bundle_fixture(tmp_path)
    past = context.model_copy(update={"now": datetime(2025, 1, 1, tzinfo=UTC)})
    with pytest.raises(ValueError, match="clock skew"):
        verify_evidence_bundle(bundle, past, root)
    finalized = context.model_copy(update={"finalized": True})
    with pytest.raises(ValueError, match="finalization"):
        verify_evidence_bundle(bundle, finalized, root)
    signer = HmacSha256TestSigner(
        signer_id="signer_test", secret=b"0123456789abcdef0123456789abcdef"
    )
    with pytest.raises(ValueError, match="requires a signed"):
        verify_evidence_bundle(bundle, context, root, signer=signer)


def test_unknown_schema_duplicate_inventory_and_reordering_are_rejected(tmp_path: Path) -> None:
    bundle, _, _ = _bundle_fixture(tmp_path)
    unknown = ArtifactSemanticIdentity(
        path="summary.csv", semantic_sha256="a" * 64, schema_version="4"
    )
    with pytest.raises(ValidationError, match="unknown schema"):
        bundle.semantic.model_copy(update={"output_artifacts": (unknown,)})
    with pytest.raises(ValidationError, match="sorted and unique"):
        bundle.semantic.model_copy(
            update={"output_artifacts": tuple(reversed(bundle.semantic.output_artifacts))}
        )
    duplicate = bundle.semantic.output_artifacts[0]
    with pytest.raises(ValidationError, match="sorted and unique"):
        bundle.semantic.model_copy(update={"output_artifacts": (duplicate, duplicate)})


def test_negative_zero_unicode_and_duplicate_json_are_canonicalized_or_rejected(
    tmp_path: Path,
) -> None:
    fact = NumericFactReference(
        fact_id="fact_zero",
        name="Cafe\u0301 return",
        artifact_path="summary.csv",
        structured_location="/rows/0/total_return",
        value=Decimal("-0.000"),
        unit="fraction",
        methodology_id="causal_daily_v3_stochastic_v2",
    )
    assert fact.value == Decimal(0)
    assert "Café" in canonical_json(fact)
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"value":1,"value":2}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON"):
        artifact_semantic_sha256(duplicate)


def test_bundle_hash_tampering_is_detected(tmp_path: Path) -> None:
    bundle, _, _ = _bundle_fixture(tmp_path)
    with pytest.raises(ValidationError, match="bundle hash"):
        bundle.model_copy(update={"bundle_hash": "f" * 64})
    with pytest.raises(ValidationError, match="semantic hash"):
        bundle.model_copy(update={"semantic_hash": "f" * 64})


def test_bundle_schema_invariants_reject_unknown_and_ambiguous_contracts(tmp_path: Path) -> None:
    bundle, _, _ = _bundle_fixture(tmp_path)
    with pytest.raises(ValidationError, match="approved command contract"):
        InvocationIdentity(normalized_arguments=("run", "--attacker", "value"))

    bad_input = bundle.semantic.input_artifacts[0].model_copy(update={"schema_version": "raw-v2"})
    with pytest.raises(ValidationError, match="input artifact uses an unknown schema"):
        bundle.semantic.model_copy(update={"input_artifacts": (bad_input,)})
    duplicate_validators = (
        bundle.semantic.validator_results[0],
        bundle.semantic.validator_results[0],
    )
    with pytest.raises(ValidationError, match="validator results must be unique"):
        bundle.semantic.model_copy(update={"validator_results": duplicate_validators})
    with pytest.raises(ValidationError, match="methodology inventory"):
        bundle.semantic.model_copy(update={"methodology_identifiers": ()})

    observations = bundle.observations
    with pytest.raises(ValidationError, match="not monotonic"):
        observations.model_copy(
            update={"execution_started_at": observations.admitted_at + timedelta(seconds=1)}
        )
    with pytest.raises(ValidationError, match="sorted and unique"):
        observations.model_copy(
            update={
                "output_artifacts": (
                    observations.output_artifacts[0],
                    observations.output_artifacts[0],
                )
            }
        )

    dropped = bundle.observations.model_copy(
        update={"output_artifacts": (bundle.observations.output_artifacts[0],)}
    )
    with pytest.raises(ValidationError, match="inventories do not match"):
        EvidenceBundle.create(bundle.semantic, dropped)
    bad_signature = HmacSha256TestSigner(signer_id="signer_test", secret=b"0123456789abcdef").sign(
        bundle.bundle_hash
    )
    bad_signature = bad_signature.model_copy(update={"signed_hash": "f" * 64})
    with pytest.raises(ValidationError, match="different hash"):
        bundle.model_copy(update={"signature": bad_signature})

    with pytest.raises(ValueError, match="sixteen"):
        HmacSha256TestSigner(signer_id="short", secret=b"short")
    signer = HmacSha256TestSigner(signer_id="expected", secret=b"0123456789abcdef")
    foreign = HmacSha256TestSigner(signer_id="foreign", secret=b"0123456789abcdef")
    with pytest.raises(ValueError, match="unexpected signer"):
        signer.verify(foreign.sign(bundle.bundle_hash))


def test_bounded_csv_and_artifact_resource_failures_are_explicit(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.csv"
    duplicate.write_text("value,value\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate headers"):
        _read_bounded_csv(duplicate)
    malformed_row = tmp_path / "row.csv"
    malformed_row.write_text("first,second\n1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="malformed row"):
        _read_bounded_csv(malformed_row)
    malformed_csv = tmp_path / "malformed.csv"
    malformed_csv.write_text('value\n"unterminated\n', encoding="utf-8")
    with pytest.raises(ValueError, match="malformed"):
        _read_bounded_csv(malformed_csv)
    missing = tmp_path / "missing.json"
    with pytest.raises(ValueError, match="regular non-symlink"):
        artifact_semantic_sha256(missing)
    oversized = tmp_path / "oversized.json"
    with oversized.open("wb") as stream:
        stream.truncate(17 * 1024 * 1024)
    with pytest.raises(ValueError, match="size limit"):
        artifact_semantic_sha256(oversized)
