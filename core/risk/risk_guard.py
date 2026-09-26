"""Fail-closed trading RiskGuard boundary."""
from dataclasses import dataclass
from datetime import datetime, timezone

from contracts.risk_guard import RiskGuardStatusSnapshot, RiskGuardStatusSource
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
        self._last_decision: RiskGuardDecision | None = None
        self._last_health_level: SensorLevel | None = None
        self._last_kill_switch_engaged: bool | None = None

    @property
    def kill_switch(self) -> KillSwitchState:
        return self._kill_switch

    def engage(self, reason: str) -> KillSwitchState:
        if not reason.strip():
            raise ValueError("KILL_SWITCH_REASON_REQUIRED")
        self._kill_switch = KillSwitchState(True, reason, datetime.now(timezone.utc))
        self._last_decision = None
        self._last_health_level = None
        self._last_kill_switch_engaged = None
        return self._kill_switch

    def reset(self) -> KillSwitchState:
        self._kill_switch = KillSwitchState(False, "RESET", datetime.now(timezone.utc))
        self._last_decision = None
        self._last_health_level = None
        self._last_kill_switch_engaged = None
        return self._kill_switch

    def evaluate(self, *, health: TradingHealthSnapshot | None,
                 kill_switch_engaged: bool | None = None) -> RiskGuardDecision:
        now = datetime.now(timezone.utc)
        engaged = self._kill_switch.engaged if kill_switch_engaged is None else kill_switch_engaged
        level = health.overall_level() if health is not None else None
        if engaged:
            decision = RiskGuardDecision(False, "KILL_SWITCH_ENGAGED", now)
        elif health is None:
            decision = RiskGuardDecision(False, "TRADING_HEALTH_UNAVAILABLE", now)
        elif level is SensorLevel.BLOCKED:
            decision = RiskGuardDecision(False, "TRADING_HEALTH_BLOCKED", now)
        elif level is SensorLevel.RED:
            decision = RiskGuardDecision(False, "TRADING_HEALTH_RED", now)
        elif level is SensorLevel.UNKNOWN:
            decision = RiskGuardDecision(False, "TRADING_HEALTH_UNKNOWN", now)
        elif level is SensorLevel.YELLOW:
            decision = RiskGuardDecision(False, "TRADING_HEALTH_DEGRADED", now)
        else:
            decision = RiskGuardDecision(True, "READY", now)
        self._last_decision = decision
        self._last_health_level = level
        self._last_kill_switch_engaged = engaged
        return decision

    def snapshot(self) -> RiskGuardStatusSnapshot | None:
        """Expose the last evaluated authoritative safety state read-only."""
        if self._last_decision is None or self._last_kill_switch_engaged is None:
            return None
        return RiskGuardStatusSnapshot(
            observed_at=self._last_decision.evaluated_at,
            admission_allowed=self._last_decision.allowed,
            kill_switch_engaged=self._last_kill_switch_engaged,
            health_level=self._last_health_level,
            reason=self._last_decision.reason,
            decision_version="1",
        )


__all__ = ["RiskGuard", "RiskGuardDecision", "RiskGuardStatusSource"]
