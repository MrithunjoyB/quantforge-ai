"""Typed role interfaces and authority enforcement."""

from typing import TYPE_CHECKING

from quantforge.roles.contracts import (
    ProviderObservationalProvenance,
    ProviderResult,
    ProviderSemanticProvenance,
    RoleAction,
    RoleAuthority,
    RoleProvider,
)

if TYPE_CHECKING:
    from quantforge.roles.orchestrator import TribunalOrchestrator


def __getattr__(name: str) -> object:
    if name == "TribunalOrchestrator":
        from quantforge.roles.orchestrator import TribunalOrchestrator

        return TribunalOrchestrator
    raise AttributeError(name)


__all__ = [
    "ProviderObservationalProvenance",
    "ProviderResult",
    "ProviderSemanticProvenance",
    "RoleAction",
    "RoleAuthority",
    "RoleProvider",
    "TribunalOrchestrator",
]
