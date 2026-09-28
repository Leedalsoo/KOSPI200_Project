"""Common market-calendar read model shared by all strategies and hubs."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


class MarketCalendarStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class MarketCalendarSnapshot:
    observed_date: date
    status: MarketCalendarStatus
    is_trading_day: bool | None
    is_holiday: bool | None
    previous_trading_day: date | None
    next_trading_day: date | None
    is_new_week_start: bool | None
    is_week_end: bool | None
    is_expiry_day: bool | None
    source: str
    source_status: str

    @property
    def available(self) -> bool:
        return self.status is MarketCalendarStatus.AVAILABLE
