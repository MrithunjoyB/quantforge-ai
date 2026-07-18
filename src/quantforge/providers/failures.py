"""Fail-closed provider failure taxonomy with safe attempt provenance."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Never

if TYPE_CHECKING:
    from quantforge.roles.contracts import ProviderAttemptObservation


class ProviderFailureKind(StrEnum):
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


class ProviderFailure(RuntimeError):
    """A sanitized terminal failure; raw transport exceptions are never retained."""

    def __init__(
        self,
        kind: ProviderFailureKind,
        *,
        attempts: tuple[ProviderAttemptObservation, ...],
        safe_detail: str,
    ) -> None:
        super().__init__(f"structured provider failed: {kind.value}: {safe_detail}")
        self.kind = kind
        self.attempts = attempts
        self.safe_detail = safe_detail

    def __reduce__(self) -> Never:
        raise TypeError("provider failures containing operational data are not serializable")


__all__ = ["ProviderFailure", "ProviderFailureKind"]
