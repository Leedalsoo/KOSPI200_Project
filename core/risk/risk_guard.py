"""Fail-closed trading RiskGuard boundary."""
from dataclasses import dataclass
from datetime import datetime, timezone

from contracts.trading_state import (
    KillSwitchState,
    SensorLevel,
    TradingHealthSnapshot,
)


@dataclass(frozen=True, slots=True)
class RiskGuardDecision:
    allowed: bool
    reason: str
    evaluated_at: datetime


class RiskGuard:
    """Blocks order admission unless safety inputs are explicitly healthy."""

    def __init__(self) -> None:
        self._kill_switch = KillSwitchState()

    @property
    def kill_switch(self) -> KillSwitchState:
        return self._kill_switch

    def engage(self, reason: str) -> KillSwitchState:
        if not reason.strip():
            raise ValueError("KILL_SWITCH_REASON_REQUIRED")
        self._kill_switch = KillSwitchState(True, reason, datetime.now(timezone.utc))
        return self._kill_switch

    def reset(self) -> KillSwitchState:
        self._kill_switch = KillSwitchState(False, "RESET", datetime.now(timezone.utc))
        return self._kill_switch

    def evaluate(self, *, health: TradingHealthSnapshot | None,
                 kill_switch_engaged: bool | None = None) -> RiskGuardDecision:
        now = datetime.now(timezone.utc)
        engaged = self._kill_switch.engaged if kill_switch_engaged is None else kill_switch_engaged
        if engaged:
            return RiskGuardDecision(False, "KILL_SWITCH_ENGAGED", now)
        if health is None:
            return RiskGuardDecision(False, "TRADING_HEALTH_UNAVAILABLE", now)
        level = health.overall_level()
        if level is SensorLevel.BLOCKED:
            return RiskGuardDecision(False, "TRADING_HEALTH_BLOCKED", now)
        if level is SensorLevel.RED:
            return RiskGuardDecision(False, "TRADING_HEALTH_RED", now)
        if level is SensorLevel.UNKNOWN:
            return RiskGuardDecision(False, "TRADING_HEALTH_UNKNOWN", now)
        if level is SensorLevel.YELLOW:
            return RiskGuardDecision(False, "TRADING_HEALTH_DEGRADED", now)
        return RiskGuardDecision(True, "READY", now)


__all__ = ["RiskGuard", "RiskGuardDecision"]
