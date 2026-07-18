"""Dependency-injected provider selection with an offline-only default."""

from __future__ import annotations

from quantforge.providers.config import CredentialSource, ProviderMode, ProviderSelection
from quantforge.providers.openai import OpenAIStructuredRoleProvider
from quantforge.roles.contracts import GovernedRoleProvider


def select_role_provider(
    selection: ProviderSelection,
    *,
    mock_provider: GovernedRoleProvider,
    credential_source: CredentialSource | None = None,
) -> GovernedRoleProvider:
    """Select exactly one provider; configuration errors never fall back to mock."""

    if selection.mode is ProviderMode.MOCK:
        return mock_provider
    if selection.openai is None:  # pragma: no cover - ProviderSelection validates this.
        raise ValueError("OpenAI provider configuration is missing")
    return OpenAIStructuredRoleProvider(
        selection.openai,
        credential_source=credential_source,
    )


__all__ = ["select_role_provider"]
