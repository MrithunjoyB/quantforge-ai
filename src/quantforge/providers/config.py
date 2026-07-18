"""Operator-owned provider selection and credential boundaries."""

from __future__ import annotations

import os
from enum import StrEnum
from typing import Protocol

from pydantic import Field, field_validator, model_validator

from quantforge.domain.models import StrictModel


class ProviderMode(StrEnum):
    MOCK = "mock"
    OPENAI = "openai"


class CredentialSource(Protocol):
    """Credentials are supplied just in time and never enter provider provenance."""

    def api_key(self) -> str: ...


class EnvironmentCredentialSource:
    """Read an API key from one fixed environment variable without retaining it."""

    __slots__ = ()

    def api_key(self) -> str:
        value = os.environ.get("OPENAI_API_KEY")
        if value is None or not value.strip():
            raise RuntimeError("OPENAI_API_KEY is required for explicit OpenAI provider mode")
        return value

    def __repr__(self) -> str:
        return "EnvironmentCredentialSource(variable='OPENAI_API_KEY', value=<redacted>)"


class OpenAIProviderConfig(StrictModel):
    """Bounded official-provider settings; no model or remote endpoint is implicit."""

    mode: ProviderMode
    model: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    timeout_seconds: int = Field(default=30, ge=1, le=120)
    maximum_retries: int = Field(default=2, ge=0, le=2)
    maximum_response_bytes: int = Field(default=256_000, ge=1_024, le=1_000_000)
    retain_raw_response_digest: bool = True

    @field_validator("model")
    @classmethod
    def model_cannot_be_a_credential(cls, value: str) -> str:
        if value.casefold().startswith("sk-"):
            raise ValueError("OpenAI model identifier resembles a credential")
        return value

    @model_validator(mode="after")
    def openai_mode_is_explicit(self) -> OpenAIProviderConfig:
        if self.mode is not ProviderMode.OPENAI:
            raise ValueError("OpenAI provider configuration requires explicit openai mode")
        return self


class ProviderSelection(StrictModel):
    """Default offline selection with no implicit network-provider fallback."""

    mode: ProviderMode = ProviderMode.MOCK
    openai: OpenAIProviderConfig | None = None

    @model_validator(mode="after")
    def selected_configuration_is_exact(self) -> ProviderSelection:
        if self.mode is ProviderMode.OPENAI:
            if self.openai is None or self.openai.mode is not ProviderMode.OPENAI:
                raise ValueError("explicit OpenAI mode requires explicit OpenAI configuration")
        elif self.openai is not None:
            raise ValueError("OpenAI configuration is forbidden while provider mode is mock")
        return self


__all__ = [
    "CredentialSource",
    "EnvironmentCredentialSource",
    "OpenAIProviderConfig",
    "ProviderMode",
    "ProviderSelection",
]
