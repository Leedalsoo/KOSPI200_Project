"""Historical Market Store adapter exposing completed daily OHLC."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from contracts.historical_market_ohlc import HistoricalDailyOHLC


class HistoricalMarketDailyOHLCProvider:
    """Aggregate canonical historical market events without synthetic fallback."""

    def __init__(self, store: Any, calendar: Any) -> None:
        if store is None or not callable(getattr(store, "records", None)):
            raise ValueError("HISTORICAL_OHLC_STORE_REQUIRED")
        if calendar is None or not callable(getattr(calendar, "prev_trading_day", None)):
            raise ValueError("HISTORICAL_OHLC_CALENDAR_REQUIRED")
        self.store = store
        self.calendar = calendar

    def get_previous_completed_day(self, *, symbol: str, observed_at: datetime) -> HistoricalDailyOHLC | None:
        target = self.calendar.prev_trading_day(observed_at.date())
        points: list[tuple[datetime, Decimal, str]] = []
        requested = str(symbol).strip()
        for record in self.store.records():
            tick = record["tick"]
            tick_symbol = tick.get("underlying_symbol") or tick.get("symbol")
            if tick_symbol != requested:
                continue
            timestamp = datetime.fromisoformat(tick["timestamp"])
            if timestamp.date() != target or timestamp > observed_at:
                continue
            price = tick.get("underlying_price")
            if price is None:
                continue
            value = Decimal(str(price))
            if value <= 0:
                continue
            points.append((timestamp, value, str(record["source"])))
        if not points:
            return None
        points.sort(key=lambda item: item[0])
        prices = [item[1] for item in points]
        return HistoricalDailyOHLC(
            symbol=requested,
            trading_date=target,
            open=prices[0],
            high=max(prices),
            low=min(prices),
            close=prices[-1],
            observed_at=points[-1][0],
            source=points[-1][2],
        )
