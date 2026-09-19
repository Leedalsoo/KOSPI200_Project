"""Historical daily OHLC adapter backed by the authoritative daily store."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from contracts.historical_market_ohlc import HistoricalDailyOHLC


class HistoricalMarketDailyOHLCProvider:
    """Expose completed daily OHLC without deriving it from intraday events."""

    def __init__(self, store: Any, calendar: Any) -> None:
        if store is None or not callable(getattr(store, "load_records", None)):
            raise ValueError("HISTORICAL_OHLC_STORE_REQUIRED")
        if calendar is None or not callable(getattr(calendar, "prev_trading_day", None)):
            raise ValueError("HISTORICAL_OHLC_CALENDAR_REQUIRED")
        self.store = store
        self.calendar = calendar

    def get_previous_completed_day(self, *, symbol: str, observed_at: datetime) -> HistoricalDailyOHLC | None:
        target = self.calendar.prev_trading_day(observed_at.date())
        requested = str(symbol).strip()
        if not requested:
            raise ValueError("HISTORICAL_OHLC_SYMBOL_REQUIRED")
        candidates: list[HistoricalDailyOHLC] = []
        for record, _provenance in self.store.load_records(symbol=requested, trading_date=target.isoformat()):
            if record.observed_at > observed_at:
                continue
            candidates.append(record)
        if not candidates:
            return None
        candidates.sort(key=lambda record: record.observed_at)
        return candidates[-1]
