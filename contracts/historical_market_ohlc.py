"""Authoritative historical daily OHLC contract for derived runtime inputs."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class HistoricalDailyOHLC:
    """One completed trading-day OHLC observation from historical market data."""

    symbol: str
    trading_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    observed_at: datetime
    source: str

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("HISTORICAL_OHLC_SYMBOL_REQUIRED")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("HISTORICAL_OHLC_PRICE_INVALID")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("HISTORICAL_OHLC_RANGE_INVALID")
        if self.observed_at.date() < self.trading_date:
            raise ValueError("HISTORICAL_OHLC_OBSERVATION_BEFORE_TRADING_DATE")
        if not self.source.strip():
            raise ValueError("HISTORICAL_OHLC_SOURCE_REQUIRED")


class HistoricalDailyOHLCProvider(Protocol):
    """Port for completed historical daily OHLC observations."""

    def get_previous_completed_day(
        self, *, symbol: str, observed_at: datetime
    ) -> HistoricalDailyOHLC | None: ...
