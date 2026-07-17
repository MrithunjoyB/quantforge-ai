"""Provider-neutral role contracts; all outputs must already be validated domain models."""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol

from pydantic import Field, model_validator

from quantforge.domain.models import (
    AdversarialReview,
    ChairExplanation,
    ExperimentProposal,
    MethodologyReview,
    ReproducibilityReview,
    ResearchClaim,
    RoleName,
    Sha256,
    StatisticalReview,
    StrictModel,
    Timestamp,
    TribunalCase,
    VerdictEligibility,
)
from quantforge.serialization.canonical import canonical_sha256

PROVIDER_CONTRACT_VERSION = "role-provider/1.0"
VALIDATION_POLICY_VERSION = "pydantic-strict/1.0"


class RoleAction(StrEnum):
    PROPOSE_PROTOCOL = "propose_protocol"
    REVIEW_METHODOLOGY = "review_methodology"
    REVIEW_STATISTICS = "review_statistics"
    REQUEST_CHALLENGE = "request_challenge"
    REVIEW_REPRODUCIBILITY = "review_reproducibility"
    EXPLAIN_VERDICT = "explain_verdict"
    MUTATE_LOCKED_PROTOCOL = "mutate_locked_protocol"
    INVENT_NUMERICAL_RESULT = "invent_numerical_result"
    EXECUTE_COMMAND = "execute_command"
    UPGRADE_VERDICT = "upgrade_verdict"
    ISSUE_TRADING_INSTRUCTION = "issue_trading_instruction"


_ALLOWED = MappingProxyType(
    {
        RoleName.RESEARCHER: frozenset({RoleAction.PROPOSE_PROTOCOL}),
        RoleName.METHODOLOGY_AUDITOR: frozenset({RoleAction.REVIEW_METHODOLOGY}),
        RoleName.STATISTICAL_REVIEWER: frozenset({RoleAction.REVIEW_STATISTICS}),
        RoleName.ADVERSARIAL_REVIEWER: frozenset({RoleAction.REQUEST_CHALLENGE}),
        RoleName.REPRODUCIBILITY_REVIEWER: frozenset({RoleAction.REVIEW_REPRODUCIBILITY}),
        RoleName.TRIBUNAL_CHAIR: frozenset({RoleAction.EXPLAIN_VERDICT}),
    }
)


class RoleAuthority:
    @staticmethod
    def require(role: RoleName, action: RoleAction) -> None:
        if action not in _ALLOWED.get(role, frozenset()):
            raise PermissionError(f"role {role.value} is not authorized for {action.value}")


class ProviderSemanticProvenance(StrictModel):
    provider_contract_version: str = Field(min_length=1, max_length=64)
    provider_identity: str = Field(min_length=1, max_length=128)
    model_snapshot: str = Field(min_length=1, max_length=128)
    prompt_template_id: str = Field(min_length=1, max_length=128)
    prompt_template_sha256: Sha256
    structured_output_schema_id: str = Field(min_length=1, max_length=128)
    structured_output_schema_sha256: Sha256
    validation_policy_version: str = Field(min_length=1, max_length=64)
    validated_response_sha256: Sha256


class ProviderObservationalProvenance(StrictModel):
    request_id: str = Field(min_length=1, max_length=200)
    response_id: str = Field(min_length=1, max_length=200)
    requested_at: Timestamp
    responded_at: Timestamp
    latency_ms: int = Field(ge=0, le=86_400_000)
    usage: dict[str, int] = Field(default_factory=dict)
    retry_count: int = Field(default=0, ge=0, le=100)
    transport_metadata: dict[str, str | int | bool] = Field(default_factory=dict)

    @model_validator(mode="after")
    def timestamps_are_monotonic(self) -> ProviderObservationalProvenance:
        if self.responded_at < self.requested_at:
            raise ValueError("provider response precedes its request")
        if any(value < 0 for value in self.usage.values()):
            raise ValueError("provider usage observations cannot be negative")
        return self


class ProviderResult[OutputT: StrictModel](StrictModel):
    semantic_provenance: ProviderSemanticProvenance
    observational_provenance: ProviderObservationalProvenance
    output: OutputT
    semantic_hash: Sha256

    @model_validator(mode="after")
    def semantic_identity_is_exact(self) -> ProviderResult[OutputT]:
        if self.semantic_provenance.validated_response_sha256 != canonical_sha256(self.output):
            raise ValueError("provider validated-response digest mismatch")
        expected = canonical_sha256(
            {
                "output": self.output,
                "provenance": self.semantic_provenance,
            }
        )
        if self.semantic_hash != expected:
            raise ValueError("provider semantic identity mismatch")
        return self


def prompt_template_identity(action: RoleAction) -> tuple[str, str]:
    template_id = f"quantforge_{action.value}_v1"
    template = {
        "action": action.value,
        "contract": PROVIDER_CONTRACT_VERSION,
        "instruction": "return one validated QuantForge domain object",
    }
    return template_id, canonical_sha256(template)


def output_schema_identity(model_type: type[StrictModel]) -> tuple[str, str]:
    schema_id = f"{model_type.__module__}.{model_type.__name__}/1.0"
    return schema_id, canonical_sha256(model_type.model_json_schema(mode="validation"))


def create_provider_result[ResultT: StrictModel](
    *,
    result_type: type[ProviderResult[ResultT]],
    action: RoleAction,
    output: ResultT,
    provider_identity: str,
    model_snapshot: str,
    observations: ProviderObservationalProvenance,
) -> ProviderResult[ResultT]:
    prompt_id, prompt_hash = prompt_template_identity(action)
    schema_id, schema_hash = output_schema_identity(type(output))
    semantic = ProviderSemanticProvenance(
        provider_contract_version=PROVIDER_CONTRACT_VERSION,
        provider_identity=provider_identity,
        model_snapshot=model_snapshot,
        prompt_template_id=prompt_id,
        prompt_template_sha256=prompt_hash,
        structured_output_schema_id=schema_id,
        structured_output_schema_sha256=schema_hash,
        validation_policy_version=VALIDATION_POLICY_VERSION,
        validated_response_sha256=canonical_sha256(output),
    )
    semantic_hash = canonical_sha256({"output": output, "provenance": semantic})
    return result_type(
        semantic_provenance=semantic,
        observational_provenance=observations,
        output=output,
        semantic_hash=semantic_hash,
    )


class RoleProvider(Protocol):
    """Providers return data and provenance; they receive no workflow or execution authority."""

    @property
    def provider_identity(self) -> str: ...

    @property
    def model_snapshot(self) -> str: ...

    def propose(self, claim: ResearchClaim) -> ProviderResult[ExperimentProposal]: ...

    def review_methodology(
        self, proposal: ExperimentProposal
    ) -> ProviderResult[MethodologyReview]: ...

    def review_statistics(self, case: TribunalCase) -> ProviderResult[StatisticalReview]: ...

    def review_adversarially(self, case: TribunalCase) -> ProviderResult[AdversarialReview]: ...

    def review_reproducibility(
        self, case: TribunalCase
    ) -> ProviderResult[ReproducibilityReview]: ...

    def explain(
        self, case: TribunalCase, eligibility: VerdictEligibility
    ) -> ProviderResult[ChairExplanation]: ...


ProviderResultAny = ProviderResult[Any]
