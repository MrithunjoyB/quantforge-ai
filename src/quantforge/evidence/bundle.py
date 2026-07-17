"""Canonical engine-evidence bundles, verification, and optional local signing."""

from __future__ import annotations

import csv
import hashlib
import hmac
import json
import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Final, Literal, Protocol, Self

from pydantic import Field, model_validator

from quantforge.domain.models import (
    EvidenceObject,
    EvidenceRelationship,
    Identifier,
    JsonValue,
    NumericFact,
    SafeArtifactPath,
    Sha256,
    StrictModel,
    Timestamp,
    Unit,
    ValidationStatus,
)
from quantforge.serialization.canonical import canonical_decimal, canonical_sha256
from quantforge.serialization.safe_json import MAX_JSON_BYTES, reject_symlink_components

CPP_REPOSITORY: Final = "MrithunjoyB/cpp-event-driven-backtester"
CPP_RELEASE: Final = "v1.0.0"
CPP_TAG_OBJECT: Final = "20ac53c5e4b61ae7b431d5bb263f246e35f8d2a2"
CPP_PEELED_TARGET: Final = "2f86b71dbc9f29dbda861942d8afbb10c04b6625"
GENESIS_BUNDLE_HASH: Final = "0" * 64
INVOCATION_CONTRACT_VERSION: Final = "1.0"
APPROVED_ARGUMENTS: Final = (
    "run",
    "--config",
    "configs/portfolio_equal_weight.json",
    "--execution-mode",
    "serial",
    "--threads",
    "1",
)
MAX_ARTIFACT_BYTES: Final = 16 * 1024 * 1024
MAX_OUTPUT_ARTIFACTS: Final = 256
MAX_CSV_ROWS: Final = 2_000_000
_FACT_LOCATION = re.compile(r"^/rows/(0|[1-9][0-9]*)/([A-Za-z0-9_]+)$")
_NONFINITE = {"nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}
_OBSERVATIONAL_JSON_FIELDS: Final = frozenset(
    {
        "actual_commit",
        "elapsed_seconds",
        "generated_at",
        "generated_at_utc",
        "git_commit_hash",
        "hostname",
        "output_directory",
        "portfolio_output_directory",
        "run_timestamp_utc",
        "source_tree_status",
        "timestamp",
        "username",
    }
)


class EngineIdentity(StrictModel):
    repository: Literal["MrithunjoyB/cpp-event-driven-backtester"] = CPP_REPOSITORY
    release: Literal["v1.0.0"] = CPP_RELEASE
    annotated_tag_object: Literal["20ac53c5e4b61ae7b431d5bb263f246e35f8d2a2"] = CPP_TAG_OBJECT
    peeled_target: Literal["2f86b71dbc9f29dbda861942d8afbb10c04b6625"] = CPP_PEELED_TARGET
    executable_sha256: Sha256


class InvocationIdentity(StrictModel):
    contract_version: Literal["1.0"] = INVOCATION_CONTRACT_VERSION
    command: Literal["approved_fixture_run"] = "approved_fixture_run"
    normalized_arguments: tuple[str, ...] = APPROVED_ARGUMENTS

    @model_validator(mode="after")
    def approved_arguments_only(self) -> Self:
        if self.normalized_arguments != APPROVED_ARGUMENTS:
            raise ValueError("invocation arguments are outside the approved command contract")
        return self


class ArtifactSemanticIdentity(StrictModel):
    path: SafeArtifactPath
    semantic_sha256: Sha256
    schema_version: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,31}$")]


class ArtifactObservation(StrictModel):
    path: SafeArtifactPath
    byte_sha256: Sha256
    size_bytes: Annotated[int, Field(ge=0, le=MAX_ARTIFACT_BYTES)]


class ValidatorResult(StrictModel):
    name: Literal["validate_results"]
    contract_version: Literal["cpp-v1.0.0"] = "cpp-v1.0.0"
    status: Literal["passed"]
    output_sha256: Sha256


class NumericFactReference(StrictModel):
    fact_id: Identifier
    name: Annotated[str, Field(min_length=1, max_length=120)]
    artifact_path: SafeArtifactPath
    structured_location: Annotated[str, Field(pattern=r"^/rows/[0-9]+/[A-Za-z0-9_]+$")]
    value: Decimal
    unit: Unit
    methodology_id: Literal["causal_daily_v3_stochastic_v2"]

    @model_validator(mode="after")
    def canonical_value(self) -> Self:
        canonical_decimal(self.value)
        if self.value.is_zero() and self.value.is_signed():
            object.__setattr__(self, "value", Decimal(0))
        return self


class EvidenceBundleSemantic(StrictModel):
    bundle_id: Identifier
    case_id: Identifier
    workflow_revision: Annotated[int, Field(ge=1)]
    constitution_id: Identifier
    constitution_hash: Sha256
    amendment_chain_hash: Sha256
    engine: EngineIdentity
    invocation: InvocationIdentity
    configuration_sha256: Sha256
    input_artifacts: tuple[ArtifactSemanticIdentity, ...]
    output_artifacts: tuple[ArtifactSemanticIdentity, ...] = Field(min_length=1)
    validator_results: tuple[ValidatorResult, ...] = Field(min_length=1)
    numeric_facts: tuple[NumericFactReference, ...] = Field(min_length=1)
    methodology_identifiers: tuple[Literal["causal_daily_v3_stochastic_v2"], ...] = (
        "causal_daily_v3_stochastic_v2",
    )
    previous_bundle_hash: Sha256 = GENESIS_BUNDLE_HASH

    @model_validator(mode="after")
    def deterministic_inventory(self) -> Self:
        input_paths = [item.path for item in self.input_artifacts]
        output_paths = [item.path for item in self.output_artifacts]
        fact_ids = [item.fact_id for item in self.numeric_facts]
        if input_paths != sorted(input_paths) or len(input_paths) != len(set(input_paths)):
            raise ValueError("input artifact inventory must be sorted and unique")
        if output_paths != sorted(output_paths) or len(output_paths) != len(set(output_paths)):
            raise ValueError("output artifact inventory must be sorted and unique")
        if len(output_paths) > MAX_OUTPUT_ARTIFACTS:
            raise ValueError("output artifact inventory exceeds its resource limit")
        if any(
            item.schema_version not in {"csv-v1", "json-v1", "raw-v1"}
            for item in self.input_artifacts
        ):
            raise ValueError("input artifact uses an unknown schema version")
        if any(
            item.schema_version not in {"1", "2", "3", "validated-v1"}
            for item in self.output_artifacts
        ):
            raise ValueError("output artifact uses an unknown schema version")
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("numeric fact identifiers must be unique")
        output_set = set(output_paths)
        if any(item.artifact_path not in output_set for item in self.numeric_facts):
            raise ValueError("numeric fact cites an undeclared output artifact")
        methodologies = {item.methodology_id for item in self.numeric_facts}
        if methodologies != set(self.methodology_identifiers):
            raise ValueError("numeric facts and methodology inventory do not match")
        if len({item.name for item in self.validator_results}) != len(self.validator_results):
            raise ValueError("validator results must be unique")
        return self


class EvidenceBundleObservations(StrictModel):
    execution_started_at: Timestamp
    execution_completed_at: Timestamp
    admitted_at: Timestamp
    input_artifacts: tuple[ArtifactObservation, ...]
    output_artifacts: tuple[ArtifactObservation, ...] = Field(min_length=1)
    stdout_sha256: Sha256
    stderr_sha256: Sha256

    @model_validator(mode="after")
    def ordered_observations(self) -> Self:
        if not (self.execution_started_at <= self.execution_completed_at <= self.admitted_at):
            raise ValueError("bundle observational timestamps are not monotonic")
        for inventory in (self.input_artifacts, self.output_artifacts):
            paths = [item.path for item in inventory]
            if paths != sorted(paths) or len(paths) != len(set(paths)):
                raise ValueError("artifact observations must be sorted and unique")
        return self


class BundleSignature(StrictModel):
    signer_id: Identifier
    algorithm: Literal["hmac-sha256-test"]
    signed_hash: Sha256
    signature: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class EvidenceBundle(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    semantic: EvidenceBundleSemantic
    observations: EvidenceBundleObservations
    semantic_hash: Sha256
    observation_hash: Sha256
    bundle_hash: Sha256
    signature: BundleSignature | None = None

    @model_validator(mode="after")
    def integrity(self) -> Self:
        semantic_hash = canonical_sha256(self.semantic)
        observation_hash = canonical_sha256(self.observations)
        bundle_hash = canonical_sha256(
            {"observation_hash": observation_hash, "semantic_hash": semantic_hash}
        )
        if self.semantic_hash != semantic_hash:
            raise ValueError("evidence-bundle semantic hash mismatch")
        if self.observation_hash != observation_hash:
            raise ValueError("evidence-bundle observation hash mismatch")
        if self.bundle_hash != bundle_hash:
            raise ValueError("evidence-bundle hash mismatch")
        semantic_inputs = {item.path for item in self.semantic.input_artifacts}
        observed_inputs = {item.path for item in self.observations.input_artifacts}
        semantic_outputs = {item.path for item in self.semantic.output_artifacts}
        observed_outputs = {item.path for item in self.observations.output_artifacts}
        if semantic_inputs != observed_inputs or semantic_outputs != observed_outputs:
            raise ValueError("semantic and observed artifact inventories do not match")
        if self.signature is not None and self.signature.signed_hash != self.bundle_hash:
            raise ValueError("bundle signature is bound to a different hash")
        return self

    @classmethod
    def create(
        cls,
        semantic: EvidenceBundleSemantic,
        observations: EvidenceBundleObservations,
        *,
        signer: BundleSigner | None = None,
    ) -> EvidenceBundle:
        semantic_hash = canonical_sha256(semantic)
        observation_hash = canonical_sha256(observations)
        bundle_hash = canonical_sha256(
            {"observation_hash": observation_hash, "semantic_hash": semantic_hash}
        )
        signature = signer.sign(bundle_hash) if signer is not None else None
        return cls(
            semantic=semantic,
            observations=observations,
            semantic_hash=semantic_hash,
            observation_hash=observation_hash,
            bundle_hash=bundle_hash,
            signature=signature,
        )


class BundleSigner(Protocol):
    """Authenticity provider; hashing alone is not an authenticity claim."""

    def sign(self, bundle_hash: str) -> BundleSignature: ...

    def verify(self, signature: BundleSignature) -> None: ...


class HmacSha256TestSigner:
    """Fixture-only local signer. Callers provide the secret; none is stored in bundles."""

    def __init__(self, *, signer_id: str, secret: bytes) -> None:
        if len(secret) < 16:
            raise ValueError("test HMAC secret must contain at least sixteen bytes")
        self._signer_id = signer_id
        self._secret = bytes(secret)

    def sign(self, bundle_hash: str) -> BundleSignature:
        signature = hmac.new(self._secret, bundle_hash.encode("ascii"), hashlib.sha256).hexdigest()
        return BundleSignature(
            signer_id=self._signer_id,
            algorithm="hmac-sha256-test",
            signed_hash=bundle_hash,
            signature=signature,
        )

    def verify(self, signature: BundleSignature) -> None:
        if signature.signer_id != self._signer_id:
            raise ValueError("bundle signature uses an unexpected signer")
        expected = self.sign(signature.signed_hash)
        if not hmac.compare_digest(signature.signature, expected.signature):
            raise ValueError("bundle signature verification failed")


class EvidenceAdmissionContext(StrictModel):
    case_id: Identifier
    workflow_revision: Annotated[int, Field(ge=1)]
    constitution_id: Identifier
    constitution_hash: Sha256
    amendment_chain_hash: Sha256
    engine: EngineIdentity
    configuration_sha256: Sha256
    input_artifacts: tuple[ArtifactSemanticIdentity, ...]
    input_artifact_observations: tuple[ArtifactObservation, ...]
    previous_bundle_hash: Sha256 = GENESIS_BUNDLE_HASH
    now: Timestamp
    max_future_skew_seconds: Annotated[int, Field(ge=0, le=900)] = 300
    finalized: bool = False
    allowed_methodologies: tuple[Literal["causal_daily_v3_stochastic_v2"], ...] = (
        "causal_daily_v3_stochastic_v2",
    )


def amendment_chain_hash(amendments: tuple[object, ...]) -> str:
    """Bind the complete ordered amendment chain, including the empty chain."""

    return canonical_sha256(amendments)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key in engine artifact: {key}")
        result[key] = value
    return result


def _strip_observational_fields(value: object, *, path: tuple[str, ...] = ()) -> object:
    if isinstance(value, dict):
        return {
            key: _strip_observational_fields(item, path=(*path, key))
            for key, item in value.items()
            if path or key not in _OBSERVATIONAL_JSON_FIELDS
        }
    if isinstance(value, list):
        return [
            _strip_observational_fields(item, path=(*path, str(index)))
            for index, item in enumerate(value)
        ]
    return value


def artifact_semantic_sha256(path: Path) -> str:
    """Hash artifact semantics while retaining volatile JSON bytes in observations."""

    _validate_regular_artifact(path)
    if path.suffix.casefold() != ".json":
        return _sha256_file(path)
    raw = path.read_text(encoding="utf-8")
    if len(raw.encode("utf-8")) > MAX_JSON_BYTES:
        raise ValueError("engine JSON artifact exceeds its resource limit")
    value = json.loads(
        raw,
        object_pairs_hook=_reject_duplicate_keys,
        parse_float=Decimal,
        parse_constant=lambda token: (_ for _ in ()).throw(
            ValueError(f"non-finite engine JSON value is forbidden: {token}")
        ),
    )
    return canonical_sha256(_strip_observational_fields(value))


def verify_evidence_bundle(
    bundle: EvidenceBundle,
    context: EvidenceAdmissionContext,
    artifact_root: Path,
    *,
    signer: BundleSigner | None = None,
) -> None:
    """Verify binding, replay protection, inventory, hashes, and numeric references."""

    if context.finalized:
        raise ValueError("evidence cannot be admitted after verdict finalization")
    semantic = bundle.semantic
    expected_bindings = (
        (semantic.case_id, context.case_id, "case"),
        (semantic.workflow_revision, context.workflow_revision, "workflow revision"),
        (semantic.constitution_id, context.constitution_id, "constitution identifier"),
        (semantic.constitution_hash, context.constitution_hash, "constitution hash"),
        (semantic.amendment_chain_hash, context.amendment_chain_hash, "amendment chain"),
        (semantic.engine, context.engine, "engine identity"),
        (semantic.configuration_sha256, context.configuration_sha256, "configuration"),
        (semantic.input_artifacts, context.input_artifacts, "input inventory"),
        (
            bundle.observations.input_artifacts,
            context.input_artifact_observations,
            "observed input inventory",
        ),
        (semantic.previous_bundle_hash, context.previous_bundle_hash, "bundle-chain parent"),
    )
    for actual, expected, label in expected_bindings:
        if actual != expected:
            raise ValueError(f"evidence bundle has a foreign or stale {label}")
    if set(semantic.methodology_identifiers) != set(context.allowed_methodologies):
        raise ValueError("evidence bundle uses an unknown methodology version")
    future_limit = context.now + timedelta(seconds=context.max_future_skew_seconds)
    timestamps = (
        bundle.observations.execution_started_at,
        bundle.observations.execution_completed_at,
        bundle.observations.admitted_at,
    )
    if any(timestamp > future_limit for timestamp in timestamps):
        raise ValueError("evidence bundle contains a timestamp beyond the allowed clock skew")
    if bundle.signature is not None:
        if signer is None:
            raise ValueError("signed evidence requires an explicit signature verifier")
        signer.verify(bundle.signature)
    elif signer is not None:
        raise ValueError("the admission policy requires a signed evidence bundle")
    _verify_artifact_inventory(bundle, artifact_root)
    _verify_numeric_facts(bundle, artifact_root)


def evidence_from_bundle(
    bundle: EvidenceBundle,
    *,
    evidence_id: str,
    claim_id: str,
    experiment_id: str,
    relationship: EvidenceRelationship = EvidenceRelationship.SUPPORTS,
) -> EvidenceObject:
    """Create validated tribunal evidence without reinterpreting engine numeric facts."""

    references = bundle.semantic.numeric_facts
    source_paths = {item.artifact_path for item in references}
    if len(source_paths) != 1:
        raise ValueError("one evidence object must cite numeric facts from one artifact")
    source_path = next(iter(source_paths))
    observed = {item.path: item for item in bundle.observations.output_artifacts}[source_path]
    facts = tuple(
        NumericFact(
            fact_id=item.fact_id,
            name=item.name,
            value=item.value,
            unit=item.unit,
        )
        for item in references
    )
    content: dict[str, JsonValue] = {
        "bundle_hash": bundle.bundle_hash,
        "facts": {item.fact_id: canonical_decimal(item.value) for item in references},
        "semantic_hash": bundle.semantic_hash,
    }
    units = tuple(dict.fromkeys(item.unit for item in references))
    return EvidenceObject(
        evidence_id=evidence_id,
        evidence_type="engine_result",
        case_id=bundle.semantic.case_id,
        claim_ids=(claim_id,),
        experiment_id=experiment_id,
        constitution_hash=bundle.semantic.constitution_hash,
        source_adapter="cpp_v1_adapter",
        source_artifact=source_path,
        source_artifact_sha256=observed.byte_sha256,
        structured_location=references[0].structured_location,
        content_sha256=canonical_sha256(content),
        created_at=bundle.observations.admitted_at,
        validation_status=ValidationStatus.VALIDATED,
        validation_method="cpp_v1_release_validators",
        content=content,
        numeric_facts=facts,
        units=units,
        assumptions=("The released engine remains the numerical authority",),
        limitations=("Synthetic fixture output is not empirical market evidence",),
        relationship=relationship,
        provenance={
            "bundle_hash": bundle.bundle_hash,
            "bundle_id": bundle.semantic.bundle_id,
            "engine_release": bundle.semantic.engine.release,
            "invocation_contract_version": bundle.semantic.invocation.contract_version,
        },
    )


def _verify_artifact_inventory(bundle: EvidenceBundle, artifact_root: Path) -> None:
    reject_symlink_components(artifact_root)
    if artifact_root.is_symlink() or not artifact_root.is_dir():
        raise ValueError("artifact root must be a regular non-symlink directory")
    root = artifact_root.resolve(strict=True)
    declared = {item.path: item for item in bundle.observations.output_artifacts}
    actual: dict[str, Path] = {}
    for candidate in sorted(root.rglob("*")):
        if candidate.is_symlink():
            raise ValueError("engine output inventory contains a symlink")
        if candidate.is_file():
            relative = candidate.relative_to(root).as_posix()
            actual[relative] = candidate
    if set(actual) != set(declared):
        missing = sorted(set(declared).difference(actual))
        extra = sorted(set(actual).difference(declared))
        raise ValueError(f"engine output inventory mismatch: missing={missing}, extra={extra}")
    semantic_by_path = {item.path: item for item in bundle.semantic.output_artifacts}
    for relative, candidate in actual.items():
        observation = declared[relative]
        if candidate.stat().st_size != observation.size_bytes:
            raise ValueError(f"engine output size mismatch: {relative}")
        if _sha256_file(candidate) != observation.byte_sha256:
            raise ValueError(f"engine output hash mismatch: {relative}")
        if artifact_semantic_sha256(candidate) != semantic_by_path[relative].semantic_sha256:
            raise ValueError(f"engine output semantic hash mismatch: {relative}")


def _verify_numeric_facts(bundle: EvidenceBundle, artifact_root: Path) -> None:
    cache: dict[str, list[dict[str, str]]] = {}
    for fact in bundle.semantic.numeric_facts:
        match = _FACT_LOCATION.fullmatch(fact.structured_location)
        if match is None:
            raise ValueError("numeric fact uses an invalid structured location")
        row_index = int(match.group(1))
        column = match.group(2)
        rows = cache.get(fact.artifact_path)
        if rows is None:
            path = artifact_root / fact.artifact_path
            if path.suffix.casefold() != ".csv":
                raise ValueError("numeric fact references must target validated CSV output")
            rows = _read_bounded_csv(path)
            cache[fact.artifact_path] = rows
        if row_index >= len(rows) or column not in rows[row_index]:
            raise ValueError("numeric fact structured location does not exist")
        raw = rows[row_index][column].strip()
        if raw.casefold() in _NONFINITE:
            raise ValueError("numeric fact references a non-finite engine value")
        try:
            actual = Decimal(raw)
        except InvalidOperation as error:
            raise ValueError("numeric fact references a malformed engine value") from error
        if canonical_decimal(actual) != canonical_decimal(fact.value):
            raise ValueError("numeric fact value does not match the admitted engine artifact")


def _read_bounded_csv(path: Path) -> list[dict[str, str]]:
    _validate_regular_artifact(path)
    rows: list[dict[str, str]] = []
    try:
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            if reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames)):
                raise ValueError("engine CSV has missing or duplicate headers")
            for index, row in enumerate(reader):
                if index >= MAX_CSV_ROWS:
                    raise ValueError("engine CSV exceeds its row limit")
                if None in row or any(value is None for value in row.values()):
                    raise ValueError("engine CSV contains a malformed row")
                rows.append({key: value for key, value in row.items() if key is not None})
    except (csv.Error, UnicodeError) as error:
        raise ValueError("engine CSV is malformed") from error
    return rows


def _validate_regular_artifact(path: Path) -> None:
    reject_symlink_components(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("engine artifact must be a regular non-symlink file")
    if path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError("engine artifact exceeds its size limit")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(128 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


__all__ = [
    "APPROVED_ARGUMENTS",
    "CPP_PEELED_TARGET",
    "CPP_RELEASE",
    "CPP_REPOSITORY",
    "CPP_TAG_OBJECT",
    "GENESIS_BUNDLE_HASH",
    "ArtifactObservation",
    "ArtifactSemanticIdentity",
    "BundleSignature",
    "BundleSigner",
    "EngineIdentity",
    "EvidenceAdmissionContext",
    "EvidenceBundle",
    "EvidenceBundleObservations",
    "EvidenceBundleSemantic",
    "HmacSha256TestSigner",
    "InvocationIdentity",
    "NumericFactReference",
    "ValidatorResult",
    "amendment_chain_hash",
    "artifact_semantic_sha256",
    "evidence_from_bundle",
    "verify_evidence_bundle",
]
