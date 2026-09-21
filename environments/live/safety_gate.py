from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

from contracts.trading_state import TradingHealthSnapshot
from core.risk.risk_guard import RiskGuard
from environments.live.contracts import LiveApproval, LiveApprovalState, LiveSafetyPolicy


@dataclass(frozen=True)
class LiveGateResult:
    allowed: bool
    reason: str


class LiveSafetyGate:
    def __init__(
        self,
        policy: LiveSafetyPolicy,
        *,
        risk_guard: RiskGuard,
        sensor_max_delay_seconds: float,
        approval_validity_seconds: float,
        now: Callable[[], datetime],
        allow_liquidation_reduction: bool,
    ):
        if risk_guard is None:
            raise ValueError("RISK_GUARD_REQUIRED")
        if sensor_max_delay_seconds < 0:
            raise ValueError("SENSOR_MAX_DELAY_INVALID")
        if approval_validity_seconds <= 0:
            raise ValueError("APPROVAL_VALIDITY_INVALID")
        if now is None:
            raise ValueError("CLOCK_REQUIRED")
        self.policy = policy
        self.risk_guard = risk_guard
        self.sensor_max_delay_seconds = sensor_max_delay_seconds
        self.approval_validity_seconds = approval_validity_seconds
        self._now = now
        self.allow_liquidation_reduction = allow_liquidation_reduction
        self._approval: LiveApproval | None = None

    def approve(self, approval: LiveApproval) -> None:
        if not approval.approved_by.strip():
            raise ValueError("approval identity is required")
        self._approval = approval

    def revoke(self) -> None:
        self._approval = None

    def _approval_is_valid(self, now: datetime) -> bool:
        try:
            approved_at = datetime.fromisoformat(self._approval.approved_at)
        except (TypeError, ValueError):
            return False
        if approved_at.tzinfo is None:
            approved_at = approved_at.replace(tzinfo=timezone.utc)
        return (now - approved_at).total_seconds() <= self.approval_validity_seconds

    def _sensors_are_fresh(self, health: TradingHealthSnapshot, now: datetime) -> bool:
        for sensor in health.sensors:
            if sensor.level.value != "GREEN" or sensor.observed_at is None:
                return False
            observed = sensor.observed_at
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
            if (now - observed).total_seconds() > self.sensor_max_delay_seconds:
                return False
        return True

    def evaluate(
        self,
        quantity: int,
        account_age_seconds: float | None = None,
        *,
        health: TradingHealthSnapshot | None = None,
        daily_pnl: Decimal | None = None,
        current_position_quantity: int | None = None,
        side: str | None = None,
        order_purpose: str | None = None,
        position_role: str | None = None,
    ) -> LiveGateResult:
        now = self._now()
        if self._approval is None:
            return LiveGateResult(False, "live approval is missing")
        if self.policy.approval_state is not LiveApprovalState.APPROVED:
            return LiveGateResult(False, "live approval state is not approved")
        if not self._approval_is_valid(now):
            return LiveGateResult(False, "live approval is expired")
        if health is None:
            return LiveGateResult(False, "TRADING_HEALTH_UNAVAILABLE")
        risk = self.risk_guard.evaluate(health=health)
        if not risk.allowed:
            return LiveGateResult(False, f"risk guard blocked: {risk.reason}")
        if not self._sensors_are_fresh(health, now):
            return LiveGateResult(False, "TRADING_HEALTH_NOT_FRESH")
        if daily_pnl is None:
            return LiveGateResult(False, "DAILY_PNL_REQUIRED")
        if daily_pnl < -Decimal(str(self.policy.max_daily_loss)):
            self.risk_guard.engage("DAILY_LOSS_LIMIT_EXCEEDED")
            return LiveGateResult(False, "DAILY_LOSS_LIMIT_EXCEEDED")
        if not self.policy.can_submit:
            return LiveGateResult(False, "live safety policy is disarmed")
        if quantity <= 0 or quantity > self.policy.max_order_quantity:
            return LiveGateResult(False, "order quantity exceeds live limit")
        if current_position_quantity is None:
            return LiveGateResult(False, "CURRENT_POSITION_QUANTITY_REQUIRED")
        reduction = order_purpose in {"LIQUIDATION", "REDUCTION", "CLOSE"} or position_role == "CLOSE"
        if current_position_quantity + quantity > self.policy.max_position_quantity and not (reduction and self.allow_liquidation_reduction):
            return LiveGateResult(False, "position quantity exceeds live limit")
        if account_age_seconds is not None and account_age_seconds > self.sensor_max_delay_seconds:
            return LiveGateResult(False, "account/position data is stale")
        return LiveGateResult(True, "approved")
