"""Code-owned provider orchestration with no workflow mutation authority."""

from __future__ import annotations

from typing import Any, TypeVar, cast

from quantforge.domain.models import (
    AdversarialReview,
    ChairExplanation,
    ExperimentProposal,
    MethodologyReview,
    ReproducibilityReview,
    ResearchClaim,
    RoleName,
    StatisticalReview,
    StrictModel,
    TribunalCase,
    VerdictEligibility,
)
from quantforge.roles.contracts import (
    PROVIDER_CONTRACT_VERSION,
    VALIDATION_POLICY_VERSION,
    ProviderResult,
    RoleAction,
    RoleAuthority,
    RoleProvider,
    output_schema_identity,
    prompt_template_identity,
)

ResultT = TypeVar("ResultT", bound=StrictModel)


class TribunalOrchestrator:
    """Validate injected role-provider results and retain their complete provenance."""

    def __init__(self, provider: RoleProvider) -> None:
        self._provider = provider
        self._results: list[ProviderResult[Any]] = []

    @property
    def provider_results(self) -> tuple[ProviderResult[Any], ...]:
        return tuple(self._results)

    @property
    def semantic_hashes(self) -> tuple[str, ...]:
        return tuple(result.semantic_hash for result in self._results)

    def propose(self, claim: ResearchClaim) -> ExperimentProposal:
        RoleAuthority.require(RoleName.RESEARCHER, RoleAction.PROPOSE_PROTOCOL)
        return self._accept(
            RoleAction.PROPOSE_PROTOCOL,
            self._provider.propose(claim),
            ExperimentProposal,
        )

    def review_methodology(self, proposal: ExperimentProposal) -> MethodologyReview:
        RoleAuthority.require(RoleName.METHODOLOGY_AUDITOR, RoleAction.REVIEW_METHODOLOGY)
        return self._accept(
            RoleAction.REVIEW_METHODOLOGY,
            self._provider.review_methodology(proposal),
            MethodologyReview,
        )

    def review_statistics(self, case: TribunalCase) -> StatisticalReview:
        RoleAuthority.require(RoleName.STATISTICAL_REVIEWER, RoleAction.REVIEW_STATISTICS)
        return self._accept(
            RoleAction.REVIEW_STATISTICS,
            self._provider.review_statistics(case),
            StatisticalReview,
        )

    def review_adversarially(self, case: TribunalCase) -> AdversarialReview:
        RoleAuthority.require(RoleName.ADVERSARIAL_REVIEWER, RoleAction.REQUEST_CHALLENGE)
        return self._accept(
            RoleAction.REQUEST_CHALLENGE,
            self._provider.review_adversarially(case),
            AdversarialReview,
        )

    def review_reproducibility(self, case: TribunalCase) -> ReproducibilityReview:
        RoleAuthority.require(
            RoleName.REPRODUCIBILITY_REVIEWER,
            RoleAction.REVIEW_REPRODUCIBILITY,
        )
        return self._accept(
            RoleAction.REVIEW_REPRODUCIBILITY,
            self._provider.review_reproducibility(case),
            ReproducibilityReview,
        )

    def explain(
        self,
        case: TribunalCase,
        eligibility: VerdictEligibility,
    ) -> ChairExplanation:
        RoleAuthority.require(RoleName.TRIBUNAL_CHAIR, RoleAction.EXPLAIN_VERDICT)
        return self._accept(
            RoleAction.EXPLAIN_VERDICT,
            self._provider.explain(case, eligibility),
            ChairExplanation,
        )

    def _accept(
        self,
        action: RoleAction,
        result: ProviderResult[ResultT],
        output_type: type[ResultT],
    ) -> ResultT:
        if not isinstance(result, ProviderResult):
            raise TypeError("role provider omitted its required result provenance")
        if not isinstance(result.output, output_type):
            raise TypeError("role provider returned an unauthorized domain output type")
        semantic = result.semantic_provenance
        prompt_id, prompt_hash = prompt_template_identity(action)
        schema_id, schema_hash = output_schema_identity(output_type)
        expected = (
            (semantic.provider_contract_version, PROVIDER_CONTRACT_VERSION, "contract"),
            (semantic.provider_identity, self._provider.provider_identity, "provider"),
            (semantic.model_snapshot, self._provider.model_snapshot, "model"),
            (semantic.prompt_template_id, prompt_id, "prompt identity"),
            (semantic.prompt_template_sha256, prompt_hash, "prompt hash"),
            (semantic.structured_output_schema_id, schema_id, "schema identity"),
            (semantic.structured_output_schema_sha256, schema_hash, "schema hash"),
            (
                semantic.validation_policy_version,
                VALIDATION_POLICY_VERSION,
                "validation policy",
            ),
        )
        for actual, required, label in expected:
            if actual != required:
                raise ValueError(f"role provider has a mismatched {label}")
        self._results.append(cast(ProviderResult[Any], result))
        return result.output


__all__ = ["TribunalOrchestrator"]
