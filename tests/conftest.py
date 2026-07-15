from __future__ import annotations

from datetime import UTC, datetime

import pytest

from quantforge.domain.models import ClaimScope, ResearchClaim
from quantforge.workflow.demo import DemoResult, run_demo


@pytest.fixture(scope="session")
def provisional_result() -> DemoResult:
    return run_demo("provisional")


@pytest.fixture
def simple_claim() -> ResearchClaim:
    return ResearchClaim(
        claim_id="claim_test",
        statement="A synthetic claim is falsifiable",
        submitted_by="test operator",
        submitted_at=datetime(2026, 1, 1, tzinfo=UTC),
        scope=ClaimScope(
            asset_classes=("synthetic",),
            universe=("SYNTHETIC",),
            start_date="2020-01-01",
            end_date="2021-01-01",
        ),
    )
