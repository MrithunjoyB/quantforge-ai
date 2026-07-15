"""Governed sequential state machine."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quantforge.workflow.machine import StateMachine

__all__ = ["StateMachine"]


def __getattr__(name: str) -> object:
    """Resolve the public state machine lazily to avoid package import cycles."""
    if name == "StateMachine":
        from quantforge.workflow.machine import StateMachine

        return StateMachine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
