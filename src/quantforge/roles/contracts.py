"""Provider-neutral role contracts; all outputs must already be validated domain models."""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol

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

if TYPE_CHECKING:
    from quantforge.roles.requests import GovernedRoleRequest

PROVIDER_CONTRACT_NAME = "quantforge-governed-role-provider"
PROVIDER_CONTRACT_VERSION = "role-provider/2.0"
RETRY_POLICY_ID = "quantforge-bounded-classified-retry"
RETRY_POLICY_VERSION = "1.0"
VALIDATION_POLICY_VERSION = "role-specific-strict/1.0"


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


_ROLE_BY_ACTION = MappingProxyType(
    {
        RoleAction.PROPOSE_PROTOCOL: RoleName.RESEARCHER,
        RoleAction.REVIEW_METHODOLOGY: RoleName.METHODOLOGY_AUDITOR,
        RoleAction.REVIEW_STATISTICS: RoleName.STATISTICAL_REVIEWER,
        RoleAction.REQUEST_CHALLENGE: RoleName.ADVERSARIAL_REVIEWER,
        RoleAction.REVIEW_REPRODUCIBILITY: RoleName.REPRODUCIBILITY_REVIEWER,
        RoleAction.EXPLAIN_VERDICT: RoleName.TRIBUNAL_CHAIR,
    }
)


class ProviderTransportOutcome(StrEnum):
    ACCEPTED = "accepted"
    TRANSPORT_FAILURE = "transport_failure"
    AUTHENTICATION_FAILURE = "authentication_failure"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    PROVIDER_REFUSAL = "provider_refusal"
    SAFETY_REFUSAL = "safety_refusal"
    TRUNCATED = "truncated"
    MALFORMED_STRUCTURED_OUTPUT = "malformed_structured_output"
    SCHEMA_VALIDATION_FAILURE = "schema_validation_failure"
    SEMANTIC_POLICY_FAILURE = "semantic_policy_failure"
    UNSUPPORTED_MODEL_CAPABILITY = "unsupported_model_capability"


class ProviderAttemptObservation(StrictModel):
    attempt_index: int = Field(ge=0, le=10)
    request_id: str | None = Field(default=None, max_length=200)
    response_id: str | None = Field(default=None, max_length=200)
    requested_at: Timestamp
    responded_at: Timestamp
    latency_ms: int = Field(ge=0, le=86_400_000)
    outcome: ProviderTransportOutcome
    provider_status: str | None = Field(default=None, max_length=100)
    retryable: bool
    usage: dict[str, int] = Field(default_factory=dict)
    rate_limit_observations: dict[str, str | int] = Field(default_factory=dict)
    refusal: bool = False
    truncated: bool = False

    @model_validator(mode="after")
    def observation_is_bounded(self) -> ProviderAttemptObservation:
        if self.responded_at < self.requested_at:
            raise ValueError("provider attempt precedes its request")
        if any(value < 0 for value in self.usage.values()):
            raise ValueError("provider attempt usage cannot be negative")
        return self


class ProviderCallContext(StrictModel):
    role: RoleName
    action: RoleAction
    case_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,127}$")
    case_revision: int = Field(ge=1, le=10_000)
    constitution_identity: Sha256
    amendment_chain_identity: Sha256
    evidence_references: tuple[str, ...] = ()
    context_item_identities: tuple[Sha256, ...]
    role_context_sha256: Sha256
    canonical_request_sha256: Sha256

    @model_validator(mode="after")
    def role_and_references_are_exact(self) -> ProviderCallContext:
        if _ROLE_BY_ACTION.get(self.action) is not self.role:
            raise ValueError("provider call role does not match its action")
        if len(self.evidence_references) != len(set(self.evidence_references)) or list(
            self.evidence_references
        ) != sorted(self.evidence_references):
            raise ValueError("provider evidence references must be unique and sorted")
        return self


class ProviderRequestProvenance(StrictModel):
    """Code-owned call identity retained for accepted and failed invocations alike."""

    provider_contract_name: str = Field(min_length=1, max_length=128)
    provider_contract_version: str = Field(min_length=1, max_length=64)
    provider_identity: str = Field(min_length=1, max_length=128)
    endpoint_class: str = Field(min_length=1, max_length=64)
    sdk_version: str = Field(min_length=1, max_length=64)
    requested_model: str = Field(min_length=1, max_length=200)
    role: RoleName
    action: RoleAction
    prompt_template_id: str = Field(min_length=1, max_length=128)
    prompt_template_version: str = Field(min_length=1, max_length=64)
    prompt_template_sha256: Sha256
    structured_output_schema_id: str = Field(min_length=1, max_length=128)
    structured_output_schema_version: str = Field(min_length=1, max_length=64)
    structured_output_schema_sha256: Sha256
    validation_policy_id: str = Field(min_length=1, max_length=128)
    validation_policy_version: str = Field(min_length=1, max_length=64)
    validation_policy_sha256: Sha256
    canonical_request_sha256: Sha256
    retry_policy_id: str = Field(min_length=1, max_length=128)
    retry_policy_version: str = Field(min_length=1, max_length=64)
    role_context_sha256: Sha256
    case_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,127}$")
    case_revision: int = Field(ge=1, le=10_000)
    constitution_identity: Sha256
    amendment_chain_identity: Sha256
    evidence_references: tuple[str, ...] = ()
    context_item_identities: tuple[Sha256, ...]

    @model_validator(mode="after")
    def role_and_references_are_exact(self) -> ProviderRequestProvenance:
        if _ROLE_BY_ACTION.get(self.action) is not self.role:
            raise ValueError("provider request provenance role does not match its action")
        if len(self.evidence_references) != len(set(self.evidence_references)) or list(
            self.evidence_references
        ) != sorted(self.evidence_references):
            raise ValueError("provider request evidence references must be unique and sorted")
        return self


class ProviderSemanticProvenance(StrictModel):
    provider_contract_name: str = Field(min_length=1, max_length=128)
    provider_contract_version: str = Field(min_length=1, max_length=64)
    provider_identity: str = Field(min_length=1, max_length=128)
    endpoint_class: str = Field(min_length=1, max_length=64)
    sdk_version: str = Field(min_length=1, max_length=64)
    requested_model: str = Field(min_length=1, max_length=200)
    model_snapshot: str = Field(min_length=1, max_length=128)
    role: RoleName
    action: RoleAction
    prompt_template_id: str = Field(min_length=1, max_length=128)
    prompt_template_version: str = Field(min_length=1, max_length=64)
    prompt_template_sha256: Sha256
    structured_output_schema_id: str = Field(min_length=1, max_length=128)
    structured_output_schema_version: str = Field(min_length=1, max_length=64)
    structured_output_schema_sha256: Sha256
    validation_policy_id: str = Field(min_length=1, max_length=128)
    validation_policy_version: str = Field(min_length=1, max_length=64)
    validation_policy_sha256: Sha256
    canonical_request_sha256: Sha256
    validated_output_sha256: Sha256
    raw_response_sha256: Sha256 | None = None
    canonical_accepted_response_sha256: Sha256
    retry_policy_id: str = Field(min_length=1, max_length=128)
    retry_policy_version: str = Field(min_length=1, max_length=64)
    role_context_sha256: Sha256
    case_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,127}$")
    case_revision: int = Field(ge=1, le=10_000)
    constitution_identity: Sha256
    amendment_chain_identity: Sha256
    evidence_references: tuple[str, ...] = ()
    context_item_identities: tuple[Sha256, ...]
    validated_response_sha256: Sha256


class ProviderObservationalProvenance(StrictModel):
    request_id: str = Field(min_length=1, max_length=200)
    response_id: str = Field(min_length=1, max_length=200)
    requested_at: Timestamp
    responded_at: Timestamp
    latency_ms: int = Field(ge=0, le=86_400_000)
    usage: dict[str, int] = Field(default_factory=dict)
    retry_count: int = Field(default=0, ge=0, le=100)
    transport_outcome: ProviderTransportOutcome = ProviderTransportOutcome.ACCEPTED
    provider_status: str | None = Field(default=None, max_length=100)
    rate_limit_observations: dict[str, str | int] = Field(default_factory=dict)
    refusal: bool = False
    truncated: bool = False
    attempts: tuple[ProviderAttemptObservation, ...] = ()
    transport_metadata: dict[str, str | int | bool] = Field(default_factory=dict)

    @model_validator(mode="after")
    def timestamps_are_monotonic(self) -> ProviderObservationalProvenance:
        if self.responded_at < self.requested_at:
            raise ValueError("provider response precedes its request")
        if any(value < 0 for value in self.usage.values()):
            raise ValueError("provider usage observations cannot be negative")
        if self.retry_count != max(0, len(self.attempts) - 1) and self.attempts:
            raise ValueError("provider retry count does not match its attempt inventory")
        if self.attempts and [attempt.attempt_index for attempt in self.attempts] != list(
            range(len(self.attempts))
        ):
            raise ValueError("provider attempts must be consecutively ordered")
        return self


class ProviderResult[OutputT: StrictModel](StrictModel):
    semantic_provenance: ProviderSemanticProvenance
    observational_provenance: ProviderObservationalProvenance
    output: OutputT
    semantic_hash: Sha256

    @model_validator(mode="after")
    def semantic_identity_is_exact(self) -> ProviderResult[OutputT]:
        output_hash = canonical_sha256(self.output)
        if self.semantic_provenance.validated_response_sha256 != output_hash:
            raise ValueError("provider validated-response digest mismatch")
        if self.semantic_provenance.validated_output_sha256 != output_hash:
            raise ValueError("provider validated-output digest mismatch")
        if self.semantic_provenance.canonical_accepted_response_sha256 != output_hash:
            raise ValueError("provider accepted-response digest mismatch")
        if self.semantic_provenance.role is not _ROLE_BY_ACTION.get(
            self.semantic_provenance.action
        ):
            raise ValueError("provider result role does not match its action")
        semantic_identity = self.semantic_provenance.model_dump(
            mode="python", exclude={"raw_response_sha256"}, exclude_none=False
        )
        expected = canonical_sha256(
            {
                "output": self.output,
                "provenance": semantic_identity,
            }
        )
        if self.semantic_hash != expected:
            raise ValueError("provider semantic identity mismatch")
        return self


def prompt_template_identity(action: RoleAction) -> tuple[str, str]:
    from quantforge.roles.governance import role_contract

    contract = role_contract(action)
    return contract.prompt_id, contract.prompt_sha256


def output_schema_identity(model_type: type[StrictModel]) -> tuple[str, str]:
    from quantforge.roles.governance import ROLE_CONTRACTS

    for contract in ROLE_CONTRACTS.values():
        if contract.output_type is model_type:
            return contract.schema_id, contract.schema_sha256
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
    requested_model: str | None = None,
    endpoint_class: str = "in_process",
    sdk_version: str = "quantforge-in-process",
    call_context: ProviderCallContext | None = None,
    raw_response_sha256: str | None = None,
) -> ProviderResult[ResultT]:
    from quantforge.evidence.bundle import amendment_chain_hash
    from quantforge.roles.governance import role_contract

    contract = role_contract(action)
    prompt_id, prompt_hash = contract.prompt_id, contract.prompt_sha256
    schema_id, schema_hash = contract.schema_id, contract.schema_sha256
    output_hash = canonical_sha256(output)
    if call_context is None:
        fallback_case = f"case_{output_hash[:24]}"
        fallback_request = canonical_sha256(
            {"action": action, "case_id": fallback_case, "output": output}
        )
        call_context = ProviderCallContext(
            role=contract.role,
            action=action,
            case_id=fallback_case,
            case_revision=1,
            constitution_identity="0" * 64,
            amendment_chain_identity=amendment_chain_hash(()),
            evidence_references=(),
            context_item_identities=(canonical_sha256(output),),
            role_context_sha256=canonical_sha256(output),
            canonical_request_sha256=fallback_request,
        )
    semantic = ProviderSemanticProvenance(
        provider_contract_name=PROVIDER_CONTRACT_NAME,
        provider_contract_version=PROVIDER_CONTRACT_VERSION,
        provider_identity=provider_identity,
        endpoint_class=endpoint_class,
        sdk_version=sdk_version,
        requested_model=requested_model or model_snapshot,
        model_snapshot=model_snapshot,
        role=call_context.role,
        action=call_context.action,
        prompt_template_id=prompt_id,
        prompt_template_version=contract.prompt_version,
        prompt_template_sha256=prompt_hash,
        structured_output_schema_id=schema_id,
        structured_output_schema_version=contract.schema_version,
        structured_output_schema_sha256=schema_hash,
        validation_policy_id=contract.validation_policy_id,
        validation_policy_version=contract.validation_policy_version,
        validation_policy_sha256=contract.validation_policy_sha256,
        canonical_request_sha256=call_context.canonical_request_sha256,
        validated_output_sha256=output_hash,
        raw_response_sha256=raw_response_sha256,
        canonical_accepted_response_sha256=output_hash,
        retry_policy_id=RETRY_POLICY_ID,
        retry_policy_version=RETRY_POLICY_VERSION,
        role_context_sha256=call_context.role_context_sha256,
        case_id=call_context.case_id,
        case_revision=call_context.case_revision,
        constitution_identity=call_context.constitution_identity,
        amendment_chain_identity=call_context.amendment_chain_identity,
        evidence_references=call_context.evidence_references,
        context_item_identities=call_context.context_item_identities,
        validated_response_sha256=output_hash,
    )
    semantic_identity = semantic.model_dump(
        mode="python", exclude={"raw_response_sha256"}, exclude_none=False
    )
    semantic_hash = canonical_sha256({"output": output, "provenance": semantic_identity})
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


class GovernedRoleProvider(Protocol):
    """Structured providers consume one complete code-owned request and have no tools."""

    @property
    def provider_identity(self) -> str: ...

    @property
    def model_snapshot(self) -> str: ...

    @property
    def endpoint_class(self) -> str: ...

    @property
    def sdk_version(self) -> str: ...

    def invoke(self, request: GovernedRoleRequest) -> ProviderResultAny: ...


RoleOutput = (
    ExperimentProposal
    | MethodologyReview
    | StatisticalReview
    | AdversarialReview
    | ReproducibilityReview
    | ChairExplanation
)

ProviderResultAny = (
    ProviderResult[ExperimentProposal]
    | ProviderResult[MethodologyReview]
    | ProviderResult[StatisticalReview]
    | ProviderResult[AdversarialReview]
    | ProviderResult[ReproducibilityReview]
    | ProviderResult[ChairExplanation]
)
