from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import pytest
from pydantic import ValidationError

from quantforge.domain.models import Money, Rate, ResearchClaim


@pytest.mark.parametrize(
    "factory",
    [
        lambda: Rate(value=Decimal("NaN"), unit="fraction"),
        lambda: Money(amount=Decimal("Infinity"), currency="USD"),
    ],
)
def test_nonfinite_financial_values_are_rejected(factory: Callable[[], object]) -> None:
    with pytest.raises(ValidationError, match="finite"):
        factory()


def test_naive_timestamp_is_rejected(simple_claim: ResearchClaim) -> None:
    data = simple_claim.model_dump(mode="python")
    data["submitted_at"] = data["submitted_at"].replace(tzinfo=None)
    with pytest.raises(ValidationError, match="timezone-aware"):
        type(simple_claim).model_validate(data)


@pytest.mark.parametrize(
    ("start_date", "end_date"),
    [("2026-02-30", "2026-03-01"), ("2026-03-02", "2026-03-01")],
)
def test_claim_scope_dates_are_real_and_ordered(
    simple_claim: ResearchClaim, start_date: str, end_date: str
) -> None:
    scope = simple_claim.scope
    data = scope.model_dump(mode="python")
    data.update(start_date=start_date, end_date=end_date)
    with pytest.raises(ValidationError, match="date"):
        type(scope).model_validate(data)


def test_extreme_decimal_magnitude_is_bounded() -> None:
    with pytest.raises(ValidationError, match="magnitude"):
        Rate(value=Decimal("1e1001"), unit="fraction")


@pytest.mark.parametrize(
    "factory",
    [
        lambda: Rate(value=Decimal("-1"), unit="basis_points"),
        lambda: Rate(value=Decimal("1.1"), unit="fraction"),
        lambda: Money(amount=Decimal("0"), currency="USD"),
    ],
)
def test_execution_values_have_scientifically_safe_ranges(factory: Callable[[], object]) -> None:
    with pytest.raises(ValidationError, match=r"range|positive"):
        factory()
