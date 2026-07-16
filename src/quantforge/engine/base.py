"""Strict adapter interface and immutable engine-run result."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from quantforge.evidence.bundle import (
    ArtifactObservation,
    ArtifactSemanticIdentity,
    BundleSigner,
    EngineIdentity,
    EvidenceBundle,
    EvidenceBundleObservations,
    EvidenceBundleSemantic,
    InvocationIdentity,
    NumericFactReference,
    ValidatorResult,
)


@dataclass(frozen=True)
class ApprovedFixtureIdentity:
    engine: EngineIdentity
    configuration_sha256: str
    input_semantics: tuple[ArtifactSemanticIdentity, ...]
    input_observations: tuple[ArtifactObservation, ...]


@dataclass(frozen=True)
class EngineRun:
    run_root: Path
    output_root: Path
    engine: EngineIdentity
    invocation: InvocationIdentity
    configuration_sha256: str
    input_semantics: tuple[ArtifactSemanticIdentity, ...]
    input_observations: tuple[ArtifactObservation, ...]
    output_semantics: tuple[ArtifactSemanticIdentity, ...]
    output_observations: tuple[ArtifactObservation, ...]
    validators: tuple[ValidatorResult, ...]
    numeric_facts: tuple[NumericFactReference, ...]
    execution_started_at: datetime
    execution_completed_at: datetime
    stdout_sha256: str
    stderr_sha256: str

    def evidence_bundle(
        self,
        *,
        bundle_id: str,
        case_id: str,
        workflow_revision: int,
        constitution_id: str,
        constitution_hash: str,
        amendment_chain_hash: str,
        previous_bundle_hash: str,
        admitted_at: datetime,
        signer: BundleSigner | None = None,
    ) -> EvidenceBundle:
        semantic = EvidenceBundleSemantic(
            bundle_id=bundle_id,
            case_id=case_id,
            workflow_revision=workflow_revision,
            constitution_id=constitution_id,
            constitution_hash=constitution_hash,
            amendment_chain_hash=amendment_chain_hash,
            engine=self.engine,
            invocation=self.invocation,
            configuration_sha256=self.configuration_sha256,
            input_artifacts=self.input_semantics,
            output_artifacts=self.output_semantics,
            validator_results=self.validators,
            numeric_facts=self.numeric_facts,
            previous_bundle_hash=previous_bundle_hash,
        )
        observations = EvidenceBundleObservations(
            execution_started_at=self.execution_started_at,
            execution_completed_at=self.execution_completed_at,
            admitted_at=admitted_at,
            input_artifacts=self.input_observations,
            output_artifacts=self.output_observations,
            stdout_sha256=self.stdout_sha256,
            stderr_sha256=self.stderr_sha256,
        )
        return EvidenceBundle.create(semantic, observations, signer=signer)


class EngineAdapter(ABC):
    """Read-only numerical-engine boundary with no command-fragment API."""

    @property
    @abstractmethod
    def allowed_commands(self) -> tuple[tuple[str, ...], ...]:
        raise NotImplementedError

    @abstractmethod
    def verify_release_identity(self) -> EngineIdentity:
        raise NotImplementedError

    @abstractmethod
    def approved_fixture_identity(self) -> ApprovedFixtureIdentity:
        raise NotImplementedError

    @abstractmethod
    def execute_approved_fixture(self) -> EngineRun:
        raise NotImplementedError
