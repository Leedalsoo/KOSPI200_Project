"""Explicit assembly for REST execution recovery into the shared Live settlement seam."""
from __future__ import annotations

from typing import Any

from environments.live.execution.live_execution_recovery_service import LiveExecutionRecoveryService


def create_live_execution_recovery_composition(
# *,
    transport: Any,
    adapter: Any,
    correlation_provider: Any,
    settlement_callback: Any,
) -> LiveExecutionRecoveryService:
    required = {
        "transport": transport,
        "adapter": adapter,
        "correlation_provider": correlation_provider,
        "settlement_callback": settlement_callback,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise ValueError("LIVE_RECOVERY_COMPOSITION_DEPENDENCY_REQUIRED:" + ",".join(missing))

    return LiveExecutionRecoveryService(
        transport=transport,
        adapter=adapter,
        correlation_provider=correlation_provider,
        on_report=settlement_callback,
    )
