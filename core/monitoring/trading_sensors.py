"""Composable health sensors with explicit, configurable freshness policy."""
from dataclasses import dataclass
from datetime import datetime, timezone

from contracts.types import ProviderHealth
from contracts.trading_state import SensorLevel, SensorSnapshot, TradingHealthSnapshot


@dataclass(frozen=True, slots=True)
class FreshnessPolicy:
    """Thresholds are supplied by the caller; no project-wide values are invented."""
    yellow_after_seconds: float
    red_after_seconds: float

    def __post_init__(self) -> None:
        if self.yellow_after_seconds < 0 or self.red_after_seconds < self.yellow_after_seconds:
            raise ValueError("FRESHNESS_POLICY_RANGE_INVALID")


def provider_health_sensor(name: str, health: ProviderHealth,
                           *, policy: FreshnessPolicy | None = None,
                           now: datetime | None = None) -> SensorSnapshot:
    """Project ProviderHealth → SensorSnapshot adapter; unavailable stays BLOCKED."""
    observed = health.observed_at or health.as_of
    if not health.available or observed is None:
        return SensorSnapshot(name, SensorLevel.BLOCKED, observed, health.reason or "UNAVAILABLE")
    if health.freshness_seconds is None:
        return SensorSnapshot(name, SensorLevel.UNKNOWN, observed, "FRESHNESS_UNKNOWN")
    if policy is None:
        return SensorSnapshot(name, SensorLevel.UNKNOWN, observed, "FRESHNESS_POLICY_REQUIRED")
    age = health.freshness_seconds
    if age > policy.red_after_seconds:
        return SensorSnapshot(name, SensorLevel.RED, observed, f"STALE:{age:.3f}s")
    if age > policy.yellow_after_seconds:
        return SensorSnapshot(name, SensorLevel.YELLOW, observed, f"DEGRADED:{age:.3f}s")
    return SensorSnapshot(name, SensorLevel.GREEN, observed, f"FRESH:{age:.3f}s")


def connection_sensor(name: str, *, connected: bool, observed_at: datetime | None = None,
                      reason: str = "") -> SensorSnapshot:
    """Explicit connection state sensor; false is never normalized to healthy."""
    level = SensorLevel.GREEN if connected else SensorLevel.BLOCKED
    return SensorSnapshot(name, level, observed_at or datetime.now(timezone.utc), reason or ("CONNECTED" if connected else "DISCONNECTED"))


def aggregate_sensors(sensors: list[SensorSnapshot]) -> TradingHealthSnapshot:
    return TradingHealthSnapshot.from_sensors(sensors)
