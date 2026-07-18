"""Second-layer semantic policy validation for role-specific structured output."""

from __future__ import annotations

from collections.abc import Iterable
from typing import cast

from quantforge.domain.models import (
    AdversarialReview,
    ChairExplanation,
    ChallengeStatus,
    ExperimentProposal,
    MethodologyReview,
    ReproducibilityReview,
    ReproducibilityStatus,
    StatisticalReview,
    StrictModel,
    TribunalCase,
)
from quantforge.roles.contracts import RoleAction
from quantforge.roles.governance import role_contract
from quantforge.roles.requests import GovernedRoleRequest

_PROHIBITED_AUTHORITY_CLAIMS = (
    "human approval granted",
    "human approval recorded",
    "constitution locked",
    "constitution amended",
    "engine run completed",
    "experiment has run",
    "trusted evidence admitted",
    "evidence admission receipt",
    "workflow advanced",
    "verdict upgraded",
    "execute command",
    "run shell",
    "access the filesystem",
    "place order",
    "trading instruction",
)


def _strings(value: object) -> Iterable[str]:
    if isinstance(value, StrictModel):
        yield from _strings(value.model_dump(mode="python"))
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, str):
        yield value


def _reject_authority_claims(output: StrictModel) -> None:
    for text in _strings(output):
        folded = text.casefold()
        if "sk-" in folded:
            raise ValueError("role output contains a prohibited credential-like value")
        if any(claim in folded for claim in _PROHIBITED_AUTHORITY_CLAIMS):
            raise ValueError("role output claims authority reserved to QuantForge code")


def _validate_references(
    references: Iterable[object], request: GovernedRoleRequest, *, required: bool
) -> None:
    evidence_allow_list = set(request.evidence_references)
    fact_allow_list = set(request.numeric_fact_references)
    count = 0
    for reference in references:
        evidence_id = getattr(reference, "evidence_id", None)
        numeric_fact_ids = getattr(reference, "numeric_fact_ids", ())
        count += 1
        if evidence_id not in evidence_allow_list:
            raise ValueError("role output fabricated or substituted an evidence identifier")
        if not set(numeric_fact_ids).issubset(fact_allow_list):
            raise ValueError("role output fabricated or substituted a numeric-fact identifier")
    if required and count == 0:
        raise ValueError("role output omitted required supplied-evidence references")


def validate_role_output(
    request: GovernedRoleRequest,
    output: StrictModel,
    *,
    case: TribunalCase,
) -> StrictModel:
    """Validate identity, evidence allow-lists, and prohibited authority for one role."""

    contract = role_contract(request.action)
    if type(output) is not contract.output_type:
        raise TypeError("role provider returned an unauthorized structured output type")
    if request.case_id != case.case_id or request.workflow_state is not case.state:
        raise ValueError("role request is bound to a foreign case or workflow state")
    _reject_authority_claims(output)

    if request.action is RoleAction.PROPOSE_PROTOCOL:
        proposal = cast(ExperimentProposal, output)
        if (
            proposal.experiment_id != request.expected_output_id
            or proposal.claim_id != case.claim.claim_id
            or proposal.proposed_at != request.effective_at
        ):
            raise ValueError("researcher output substituted a code-owned identity or timestamp")
        if not proposal.metrics or not proposal.data_requirements or not proposal.benchmarks:
            raise ValueError("researcher output omitted variables, evidence, or controls")
        if not proposal.execution_assumptions or not proposal.failure_criteria:
            raise ValueError("researcher output omitted assumptions or falsification criteria")

    elif request.action is RoleAction.REVIEW_METHODOLOGY:
        methodology_review = cast(MethodologyReview, output)
        if case.proposal is None:
            raise ValueError("methodology review lacks its governed proposal")
        if (
            methodology_review.review_id != request.expected_output_id
            or methodology_review.experiment_id != case.proposal.experiment_id
            or methodology_review.reviewed_at != request.effective_at
        ):
            raise ValueError("methodology output substituted a code-owned identity or timestamp")
        _validate_references(
            (
                reference
                for finding in methodology_review.findings
                for reference in finding.evidence_references
            ),
            request,
            required=False,
        )

    elif request.action is RoleAction.REVIEW_STATISTICS:
        statistical_review = cast(StatisticalReview, output)
        if (
            statistical_review.review_id != request.expected_output_id
            or statistical_review.reviewed_at != request.effective_at
        ):
            raise ValueError("statistical output substituted a code-owned identity or timestamp")
        if not statistical_review.findings:
            raise ValueError("statistical output requires at least one evidence-backed finding")
        for finding in statistical_review.findings:
            _validate_references(finding.evidence_references, request, required=True)

    elif request.action is RoleAction.REQUEST_CHALLENGE:
        adversarial_review = cast(AdversarialReview, output)
        if (
            adversarial_review.review_id != request.expected_output_id
            or adversarial_review.reviewed_at != request.effective_at
        ):
            raise ValueError("adversarial output substituted a code-owned identity or timestamp")
        for challenge in adversarial_review.challenges:
            _validate_references(
                challenge.evidence_references,
                request,
                required=challenge.status is ChallengeStatus.FAILED,
            )
        _validate_references(
            (
                reference
                for finding in adversarial_review.findings
                for reference in finding.evidence_references
            ),
            request,
            required=False,
        )

    elif request.action is RoleAction.REVIEW_REPRODUCIBILITY:
        reproducibility_review = cast(ReproducibilityReview, output)
        if (
            reproducibility_review.review_id != request.expected_output_id
            or reproducibility_review.reviewed_at != request.effective_at
        ):
            raise ValueError(
                "reproducibility output substituted a code-owned identity or timestamp"
            )
        checks = (
            reproducibility_review.configuration_verified,
            reproducibility_review.manifests_verified,
            reproducibility_review.hashes_verified,
            reproducibility_review.software_identity_verified,
            reproducibility_review.data_lineage_verified,
            reproducibility_review.evidence_complete,
        )
        if (
            reproducibility_review.status is ReproducibilityStatus.VERIFIED or any(checks)
        ) and not request.code_owned_reproducibility_verified:
            raise PermissionError(
                "provider cannot mark reproducibility without code-owned verification"
            )
        _validate_references(
            (
                reference
                for finding in reproducibility_review.findings
                for reference in finding.evidence_references
            ),
            request,
            required=False,
        )

    elif request.action is RoleAction.EXPLAIN_VERDICT:
        explanation = cast(ChairExplanation, output)
        eligibility = case.verdict_eligibility
        if eligibility is None:
            raise ValueError("Chair output lacks deterministic verdict eligibility")
        if (
            explanation.explanation_id != request.expected_output_id
            or explanation.created_at != request.effective_at
        ):
            raise ValueError("Chair output substituted a code-owned identity or timestamp")
        if explanation.computed_verdict is not eligibility.verdict:
            raise PermissionError("Chair cannot alter the deterministic verdict")
        if (
            explanation.decisive_evidence != eligibility.decisive_evidence
            or explanation.contradictory_evidence != eligibility.contradictory_evidence
        ):
            raise PermissionError("Chair cannot alter deterministic evidence sets")
        _validate_references(explanation.decisive_evidence, request, required=True)
        _validate_references(explanation.contradictory_evidence, request, required=False)
    else:  # pragma: no cover - the governed contract registry is closed above.
        raise ValueError("unsupported governed role action")

    return output


__all__ = ["validate_role_output"]
