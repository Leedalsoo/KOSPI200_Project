from datetime import datetime, timezone

from contracts.risk_guard import RiskGuardStatusSnapshot
from contracts.trading_state import SensorLevel


class StaticRiskGuardStatusSource:
    def __init__(self, allowed: bool | None, reason: str = "TEST") -> None:
        self.allowed = allowed
        self.reason = reason

    def snapshot(self):
        if self.allowed is None:
            return None
        return RiskGuardStatusSnapshot(
            observed_at=datetime.now(timezone.utc),
            admission_allowed=self.allowed,
            kill_switch_engaged=not self.allowed,
            health_level=SensorLevel.GREEN if self.allowed else SensorLevel.RED,
            reason=self.reason,
            decision_version="test",
        )


def allow_risk_guard():
    return StaticRiskGuardStatusSource(True, "TEST_READY")
