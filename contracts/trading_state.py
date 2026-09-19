"""Environment-neutral trading health, exposure and safety state contracts."""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Iterable


class SensorLevel(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class SensorSnapshot:
    name: str
    level: SensorLevel
    observed_at: datetime | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("SENSOR_NAME_REQUIRED")
        if self.observed_at is None:
            object.__setattr__(self, "observed_at", datetime.now(timezone.utc))


@dataclass(frozen=True, slots=True)
class TradingHealthSnapshot:
    observed_at: datetime
    sensors: tuple[SensorSnapshot, ...]

    @classmethod
    def from_sensors(cls, sensors: Iterable[SensorSnapshot]) -> "TradingHealthSnapshot":
        values = tuple(sensors)
        if not values:
            raise ValueError("TRADING_HEALTH_SENSORS_REQUIRED")
        return cls(datetime.now(timezone.utc), values)

    def overall_level(self) -> SensorLevel:
        levels = {sensor.level for sensor in self.sensors}
        if SensorLevel.BLOCKED in levels:
            return SensorLevel.BLOCKED
        if SensorLevel.RED in levels:
            return SensorLevel.RED
        if SensorLevel.UNKNOWN in levels:
            return SensorLevel.UNKNOWN
        if SensorLevel.YELLOW in levels:
            return SensorLevel.YELLOW
        return SensorLevel.GREEN


@dataclass(frozen=True, slots=True)
class PositionPnLExposureSnapshot:
    """Explicit read model; no missing value is converted to a synthetic zero."""

    as_of: datetime
    gross_exposure: Decimal | None
    net_exposure: Decimal | None
    option_exposure: Decimal | None
    futures_exposure: Decimal | None
    realized_pnl: Decimal | None
    unrealized_pnl: Decimal | None
    daily_pnl: Decimal | None
    open_positions: int | None


@dataclass(frozen=True, slots=True)
class KillSwitchState:
    engaged: bool = True
    reason: str = "FAIL_SAFE_DEFAULT"
    engaged_at: datetime | None = None


__all__ = [
    "KillSwitchState",
    "PositionPnLExposureSnapshot",
    "SensorLevel",
    "SensorSnapshot",
    "TradingHealthSnapshot",
]
