"""Chair boundary: explain a policy verdict without choosing or escalating it."""

from __future__ import annotations

from datetime import datetime
from types import MappingProxyType

from quantforge.domain.models import (
    ChairExplanation,
    Verdict,
    VerdictEligibility,
)

_STRENGTH = MappingProxyType(
    {
        Verdict.REJECTED: 0,
        Verdict.INCONCLUSIVE: 1,
        Verdict.FRAGILE: 2,
        Verdict.PROVISIONALLY_SUPPORTED: 3,
        Verdict.SUPPORTED: 4,
    }
)


def create_chair_explanation(
    *,
    explanation_id: str,
    eligibility: VerdictEligibility,
    requested_verdict: Verdict,
    summary: str,
    limitations: tuple[str, ...],
    verdict_change_conditions: tuple[str, ...],
    created_at: datetime,
) -> ChairExplanation:
    if _STRENGTH[requested_verdict] > _STRENGTH[eligibility.verdict]:
        raise PermissionError("Chair cannot upgrade the deterministic policy verdict")
    if requested_verdict is not eligibility.verdict:
        raise ValueError("Chair explanation must report the exact computed verdict")
    return ChairExplanation(
        explanation_id=explanation_id,
        computed_verdict=eligibility.verdict,
        summary=summary,
        decisive_evidence=eligibility.decisive_evidence,
        contradictory_evidence=eligibility.contradictory_evidence,
        limitations=limitations,
        verdict_change_conditions=verdict_change_conditions,
        created_at=created_at,
    )
