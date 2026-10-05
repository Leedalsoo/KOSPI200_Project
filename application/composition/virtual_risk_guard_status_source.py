from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from contracts.risk_guard import RiskGuardStatusSnapshot
from contracts.trading_state import SensorLevel


class VirtualRiskGuardStatusSource:
    """Authoritative safety-status source for the Virtual runtime only.

    Admission is allowed only while the owning RuntimeController reports RUNNING.
    This source is an execution-safety boundary, not a market-data fallback.
    """

    source_name = "VirtualRuntime:RiskGuard"

    def __init__(self, runtime_controller: Any) -> None:
        self._runtime_controller = runtime_controller

    def snapshot(self) -> RiskGuardStatusSnapshot:
        status = self._runtime_controller.status()
        running = str(getattr(status, "state", "")).upper() == "RUNNING"
        return RiskGuardStatusSnapshot(
            observed_at=datetime.now(timezone.utc),
            admission_allowed=running,
            kill_switch_engaged=not running,
            health_level=SensorLevel.GREEN if running else SensorLevel.RED,
            reason="VIRTUAL_RUNTIME_READY" if running else "VIRTUAL_RUNTIME_NOT_RUNNING",
            decision_version="virtual-1",
        )
