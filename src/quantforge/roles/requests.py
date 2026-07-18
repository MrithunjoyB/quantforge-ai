"""Code-owned, role-minimal request construction and context isolation."""

from __future__ import annotations

import unicodedata
from enum import StrEnum
from typing import Annotated, Final

from pydantic import AfterValidator, Field, model_validator

from quantforge.domain.models import (
    Identifier,
    RoleName,
    Sha256,
    StrictModel,
    Timestamp,
    TribunalCase,
    WorkflowState,
)
from quantforge.evidence.bundle import amendment_chain_hash
from quantforge.roles.contracts import PROVIDER_CONTRACT_VERSION, RoleAction
from quantforge.roles.governance import role_contract
from quantforge.serialization.canonical import canonical_json, canonical_sha256

MAX_CONTEXT_ITEMS: Final = 32
MAX_CONTEXT_ITEM_CHARACTERS: Final = 12_000
APPROXIMATE_CHARACTERS_PER_TOKEN: Final = 4
EMPTY_CONSTITUTION_IDENTITY: Final = "0" * 64


def _strict_unicode(value: str) -> str:
    if unicodedata.normalize("NFC", value) != value:
        raise ValueError("context text must already use NFC normalization")
    if any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs", "Co", "Cn"} for character in value
    ):
        raise ValueError("context text contains a forbidden Unicode code point")
    return value


ContextText = Annotated[
    str,
    Field(min_length=1, max_length=MAX_CONTEXT_ITEM_CHARACTERS),
    AfterValidator(_strict_unicode),
]


class ContextKind(StrEnum):
    USER_CLAIM = "untrusted_user_claim"
    PROPOSAL = "untrusted_proposal"
    PRIOR_REVIEW = "untrusted_prior_role_output"
    EVIDENCE_SUMMARY = "untrusted_evidence_summary"
    CODE_OBSERVATION = "code_owned_observation"
    VERDICT_ELIGIBILITY = "code_owned_verdict_eligibility"


class EvidenceSummary(StrictModel):
    case_id: Identifier
    case_revision: int = Field(ge=1, le=10_000)
    constitution_identity: Sha256
    amendment_chain_identity: Sha256
    evidence_id: Identifier
    numeric_fact_ids: tuple[Identifier, ...] = ()
    summary: ContextText

    @model_validator(mode="after")
    def identifiers_are_unique(self) -> EvidenceSummary:
        if len(self.numeric_fact_ids) != len(set(self.numeric_fact_ids)):
            raise ValueError("evidence-summary numeric-fact identifiers must be unique")
        return self


class RoleContextItem(StrictModel):
    kind: ContextKind
    identity: Sha256
    content: ContextText


class GovernedRoleRequest(StrictModel):
    provider_contract_version: str = Field(min_length=1, max_length=64)
    role: RoleName
    action: RoleAction
    case_id: Identifier
    case_revision: int = Field(ge=1, le=10_000)
    workflow_state: WorkflowState
    constitution_identity: Sha256
    amendment_chain_identity: Sha256
    expected_output_id: Identifier
    effective_at: Timestamp
    prompt_template_id: str = Field(min_length=1, max_length=128)
    prompt_template_version: str = Field(min_length=1, max_length=64)
    prompt_template_sha256: Sha256
    structured_output_schema_id: str = Field(min_length=1, max_length=128)
    structured_output_schema_version: str = Field(min_length=1, max_length=64)
    structured_output_schema_sha256: Sha256
    validation_policy_id: str = Field(min_length=1, max_length=128)
    validation_policy_version: str = Field(min_length=1, max_length=64)
    validation_policy_sha256: Sha256
    context: tuple[RoleContextItem, ...] = Field(min_length=1, max_length=MAX_CONTEXT_ITEMS)
    evidence_references: tuple[Identifier, ...]
    numeric_fact_references: tuple[Identifier, ...]
    code_owned_reproducibility_verified: bool = False
    maximum_context_characters: int = Field(ge=1, le=100_000)
    maximum_output_tokens: int = Field(ge=1, le=32_000)
    approximate_input_token_budget: int = Field(ge=1, le=32_000)
    context_identity: Sha256
    request_semantic_sha256: Sha256

    @model_validator(mode="after")
    def identity_and_budget_are_exact(self) -> GovernedRoleRequest:
        contract = role_contract(self.action)
        expected = (
            (self.role, contract.role, "role"),
            (self.prompt_template_id, contract.prompt_id, "prompt identity"),
            (self.prompt_template_version, contract.prompt_version, "prompt version"),
            (self.prompt_template_sha256, contract.prompt_sha256, "prompt hash"),
            (self.structured_output_schema_id, contract.schema_id, "schema identity"),
            (self.structured_output_schema_version, contract.schema_version, "schema version"),
            (self.structured_output_schema_sha256, contract.schema_sha256, "schema hash"),
            (self.validation_policy_id, contract.validation_policy_id, "policy identity"),
            (
                self.validation_policy_version,
                contract.validation_policy_version,
                "policy version",
            ),
            (
                self.validation_policy_sha256,
                contract.validation_policy_sha256,
                "policy hash",
            ),
        )
        for actual, required, label in expected:
            if actual != required:
                raise ValueError(f"governed request has a mismatched {label}")
        if list(self.context) != sorted(self.context, key=lambda item: (item.kind, item.identity)):
            raise ValueError("role context must use deterministic ordering")
        if len(self.evidence_references) != len(set(self.evidence_references)) or list(
            self.evidence_references
        ) != sorted(self.evidence_references):
            raise ValueError("evidence references must be unique and sorted")
        if len(self.numeric_fact_references) != len(set(self.numeric_fact_references)) or list(
            self.numeric_fact_references
        ) != sorted(self.numeric_fact_references):
            raise ValueError("numeric-fact references must be unique and sorted")
        context_characters = sum(len(item.content) for item in self.context)
        if context_characters > self.maximum_context_characters:
            raise ValueError("role context exceeds its explicit character budget")
        if context_characters > (
            self.approximate_input_token_budget * APPROXIMATE_CHARACTERS_PER_TOKEN
        ):
            raise ValueError("role context exceeds its explicit approximate token budget")
        if self.context_identity != canonical_sha256(self.context):
            raise ValueError("role-context identity mismatch")
        semantic = self.model_dump(
            mode="python", exclude={"request_semantic_sha256"}, exclude_none=False
        )
        if self.request_semantic_sha256 != canonical_sha256(semantic):
            raise ValueError("governed request semantic identity mismatch")
        return self

    def provider_input(self) -> tuple[dict[str, str], ...]:
        """Return separate instruction and untrusted-data messages for the official SDK."""

        contract = role_contract(self.action)
        envelope = {
            "binding": {
                "action": self.action,
                "amendment_chain_identity": self.amendment_chain_identity,
                "case_id": self.case_id,
                "case_revision": self.case_revision,
                "code_owned_reproducibility_verified": (self.code_owned_reproducibility_verified),
                "constitution_identity": self.constitution_identity,
                "effective_at": self.effective_at,
                "evidence_references": self.evidence_references,
                "expected_output_id": self.expected_output_id,
                "numeric_fact_references": self.numeric_fact_references,
                "role": self.role,
                "workflow_state": self.workflow_state,
            },
            "untrusted_context": self.context,
        }
        return (
            {"role": "system", "content": contract.prompt},
            {"role": "user", "content": canonical_json(envelope)},
        )


_EXPECTED_STATE = {
    RoleAction.PROPOSE_PROTOCOL: WorkflowState.CLAIM_RECEIVED,
    RoleAction.REVIEW_METHODOLOGY: WorkflowState.RESEARCHER_PROTOCOL_PROPOSED,
    RoleAction.REVIEW_STATISTICS: WorkflowState.EXPERIMENT_EXECUTED,
    RoleAction.REQUEST_CHALLENGE: WorkflowState.STATISTICS_REVIEWED,
    RoleAction.REVIEW_REPRODUCIBILITY: WorkflowState.OPTIONAL_FOLLOW_UP,
    RoleAction.EXPLAIN_VERDICT: WorkflowState.VERDICT_ELIGIBILITY_COMPUTED,
}


class RoleRequestBuilder:
    """Expose only deterministic, role-minimal, explicitly labelled case context."""

    def build(
        self,
        *,
        action: RoleAction,
        case: TribunalCase,
        case_revision: int,
        effective_at: Timestamp,
        evidence_summaries: tuple[EvidenceSummary, ...] = (),
        code_owned_reproducibility_verified: bool = False,
    ) -> GovernedRoleRequest:
        contract = role_contract(action)
        expected_state = _EXPECTED_STATE[action]
        if case.state is not expected_state:
            raise ValueError(f"role {contract.role.value} is not eligible at {case.state.value}")
        constitution_identity = (
            EMPTY_CONSTITUTION_IDENTITY
            if case.constitution is None
            else case.constitution.constitution_hash
        )
        amendment_identity = amendment_chain_hash(case.amendments)
        summaries = self._validate_evidence_summaries(
            case=case,
            case_revision=case_revision,
            constitution_identity=constitution_identity,
            amendment_chain_identity=amendment_identity,
            evidence_summaries=evidence_summaries,
        )
        items = self._context_for(action, case, summaries, code_owned_reproducibility_verified)
        items = tuple(sorted(items, key=lambda item: (item.kind, item.identity)))
        evidence_references = tuple(sorted(summary.evidence_id for summary in summaries))
        numeric_fact_references = tuple(
            sorted(fact_id for summary in summaries for fact_id in summary.numeric_fact_ids)
        )
        if contract.evidence_references_required and not evidence_references:
            raise ValueError(f"role {contract.role.value} requires supplied evidence references")
        output_seed = canonical_sha256(
            {
                "action": action,
                "case_id": case.case_id,
                "case_revision": case_revision,
                "context": items,
            }
        )
        prefix = "experiment" if action is RoleAction.PROPOSE_PROTOCOL else contract.role.value
        expected_output_id = f"{prefix}_{output_seed[:24]}"
        values = {
            "provider_contract_version": PROVIDER_CONTRACT_VERSION,
            "role": contract.role,
            "action": action,
            "case_id": case.case_id,
            "case_revision": case_revision,
            "workflow_state": case.state,
            "constitution_identity": constitution_identity,
            "amendment_chain_identity": amendment_identity,
            "expected_output_id": expected_output_id,
            "effective_at": effective_at,
            "prompt_template_id": contract.prompt_id,
            "prompt_template_version": contract.prompt_version,
            "prompt_template_sha256": contract.prompt_sha256,
            "structured_output_schema_id": contract.schema_id,
            "structured_output_schema_version": contract.schema_version,
            "structured_output_schema_sha256": contract.schema_sha256,
            "validation_policy_id": contract.validation_policy_id,
            "validation_policy_version": contract.validation_policy_version,
            "validation_policy_sha256": contract.validation_policy_sha256,
            "context": items,
            "evidence_references": evidence_references,
            "numeric_fact_references": numeric_fact_references,
            "code_owned_reproducibility_verified": code_owned_reproducibility_verified,
            "maximum_context_characters": contract.maximum_context_characters,
            "maximum_output_tokens": contract.maximum_output_tokens,
            "approximate_input_token_budget": (
                contract.maximum_context_characters // APPROXIMATE_CHARACTERS_PER_TOKEN
            ),
            "context_identity": canonical_sha256(items),
        }
        values["request_semantic_sha256"] = canonical_sha256(values)
        return GovernedRoleRequest.model_validate(values)

    def _validate_evidence_summaries(
        self,
        *,
        case: TribunalCase,
        case_revision: int,
        constitution_identity: str,
        amendment_chain_identity: str,
        evidence_summaries: tuple[EvidenceSummary, ...],
    ) -> tuple[EvidenceSummary, ...]:
        ordered = tuple(sorted(evidence_summaries, key=lambda item: item.evidence_id))
        if len(ordered) != len({item.evidence_id for item in ordered}):
            raise ValueError("evidence summaries must use unique evidence identifiers")
        allow_list = set(case.evidence_ids)
        for summary in ordered:
            if (
                summary.case_id != case.case_id
                or summary.case_revision != case_revision
                or summary.constitution_identity != constitution_identity
                or summary.amendment_chain_identity != amendment_chain_identity
            ):
                raise ValueError(
                    "evidence summary is bound to a foreign case, revision, or amendment chain"
                )
            if summary.evidence_id not in allow_list:
                raise ValueError("evidence summary identifier is not admitted in this case")
        return ordered

    def _context_for(
        self,
        action: RoleAction,
        case: TribunalCase,
        summaries: tuple[EvidenceSummary, ...],
        code_owned_reproducibility_verified: bool,
    ) -> tuple[RoleContextItem, ...]:
        values: list[tuple[ContextKind, object]] = [(ContextKind.USER_CLAIM, case.claim)]
        if action is not RoleAction.PROPOSE_PROTOCOL:
            if case.proposal is None:
                raise ValueError("role request requires the governed proposal")
            values.append((ContextKind.PROPOSAL, case.proposal))
        if (
            action
            in {
                RoleAction.REQUEST_CHALLENGE,
                RoleAction.REVIEW_REPRODUCIBILITY,
                RoleAction.EXPLAIN_VERDICT,
            }
            and case.statistical_review is not None
        ):
            values.append((ContextKind.PRIOR_REVIEW, case.statistical_review))
        if action in {RoleAction.REVIEW_REPRODUCIBILITY, RoleAction.EXPLAIN_VERDICT}:
            if case.adversarial_review is not None:
                values.append((ContextKind.PRIOR_REVIEW, case.adversarial_review))
            values.append(
                (
                    ContextKind.CODE_OBSERVATION,
                    {"code_owned_reproducibility_verified": (code_owned_reproducibility_verified)},
                )
            )
        if action is RoleAction.EXPLAIN_VERDICT:
            if case.methodology_review is not None:
                values.append((ContextKind.PRIOR_REVIEW, case.methodology_review))
            if case.reproducibility_review is not None:
                values.append((ContextKind.PRIOR_REVIEW, case.reproducibility_review))
        if action is RoleAction.EXPLAIN_VERDICT:
            if case.verdict_eligibility is None:
                raise ValueError("Chair request requires deterministic verdict eligibility")
            values.append((ContextKind.VERDICT_ELIGIBILITY, case.verdict_eligibility))
        values.extend((ContextKind.EVIDENCE_SUMMARY, summary) for summary in summaries)
        return tuple(
            RoleContextItem(
                kind=kind,
                identity=canonical_sha256(value),
                content=canonical_json(value),
            )
            for kind, value in values
        )


__all__ = [
    "EMPTY_CONSTITUTION_IDENTITY",
    "EvidenceSummary",
    "GovernedRoleRequest",
    "RoleContextItem",
    "RoleRequestBuilder",
]
