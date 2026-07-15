"""Provider-neutral adapters. Phase 1 includes deterministic mocks only."""

from quantforge.adapters.mock import MockEvidenceAdapter, MockRoleProvider, load_scenario

__all__ = ["MockEvidenceAdapter", "MockRoleProvider", "load_scenario"]
