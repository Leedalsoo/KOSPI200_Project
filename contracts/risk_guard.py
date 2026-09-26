"""Authoritative RiskGuard status read model and source port."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from contracts.trading_state import SensorLevel


@dataclass(frozen=True, slots=True)
class RiskGuardStatusSnapshot:
    """Immutable read model owned by the RiskGuard safety boundary."""

    observed_at: datetime
    admission_allowed: bool
    kill_switch_engaged: bool
    health_level: SensorLevel | None
    reason: str
    decision_version: str


class RiskGuardStatusSource(Protocol):
    """Read-only port for authoritative RiskGuard status consumers."""

    def snapshot(self) -> RiskGuardStatusSnapshot | None:
        ...


__all__ = ["RiskGuardStatusSnapshot", "RiskGuardStatusSource"]
