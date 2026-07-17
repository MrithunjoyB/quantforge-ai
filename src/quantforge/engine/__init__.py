"""Read-only adapters for the protected numerical engine."""

from quantforge.engine.base import ApprovedFixtureIdentity, EngineAdapter, EngineRun
from quantforge.engine.local_cpp import LocalCppV1Adapter
from quantforge.engine.trust import (
    ADAPTER_CONTRACT_VERSION,
    TrustedEngineExecution,
    TrustedExecutionReceipt,
    TrustedReceiptRecord,
)

__all__ = [
    "ADAPTER_CONTRACT_VERSION",
    "ApprovedFixtureIdentity",
    "EngineAdapter",
    "EngineRun",
    "LocalCppV1Adapter",
    "TrustedEngineExecution",
    "TrustedExecutionReceipt",
    "TrustedReceiptRecord",
]
