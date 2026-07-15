from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from quantforge.domain.models import Money, Rate


@pytest.mark.parametrize(
    "factory",
    [
        lambda: Rate(value=Decimal("NaN"), unit="fraction"),
        lambda: Money(amount=Decimal("Infinity"), currency="USD"),
    ],
)
def test_nonfinite_financial_values_are_rejected(factory: object) -> None:
    with pytest.raises(ValidationError, match="finite"):
        factory()  # type: ignore[operator]


def test_naive_timestamp_is_rejected(simple_claim: object) -> None:
    data = simple_claim.model_dump(mode="python")
    data["submitted_at"] = data["submitted_at"].replace(tzinfo=None)
    with pytest.raises(ValidationError, match="timezone-aware"):
        type(simple_claim).model_validate(data)
