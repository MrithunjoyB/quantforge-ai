"""Explicitly configured, authority-free structured role providers."""

from quantforge.providers.config import (
    EnvironmentCredentialSource,
    OpenAIProviderConfig,
    ProviderMode,
    ProviderSelection,
)
from quantforge.providers.factory import select_role_provider
from quantforge.providers.failures import ProviderFailure, ProviderFailureKind
from quantforge.providers.openai import OpenAIStructuredRoleProvider

__all__ = [
    "EnvironmentCredentialSource",
    "OpenAIProviderConfig",
    "OpenAIStructuredRoleProvider",
    "ProviderFailure",
    "ProviderFailureKind",
    "ProviderMode",
    "ProviderSelection",
    "select_role_provider",
]
