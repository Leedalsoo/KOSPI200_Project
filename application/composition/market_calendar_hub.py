"""Common Market Calendar Hub / read model for all runtime consumers."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from contracts.market_calendar import MarketCalendarSnapshot, MarketCalendarStatus


class MarketCalendarHub:
    """Own the common market-calendar decision boundary."""

    def __init__(self, calendar: Any | None) -> None:
        self._calendar = calendar

    @property
    def calendar(self) -> Any:
        return self._calendar

    def snapshot(
        self, observed_date: date, *, expiry: date | None = None
    ) -> MarketCalendarSnapshot:
        if self._calendar is None:
            return MarketCalendarSnapshot(
                observed_date=observed_date,
                status=MarketCalendarStatus.UNKNOWN,
                is_trading_day=None,
                is_holiday=None,
                previous_trading_day=None,
                next_trading_day=None,
                is_new_week_start=None,
                is_week_end=None,
                is_expiry_day=None,
                source="UNKNOWN",
                source_status="UNKNOWN:CALENDAR_NOT_COMPOSED",
            )
        try:
            is_trading = self._calendar.is_trading_day(observed_date)
            previous = self._calendar.prev_trading_day(observed_date)
            next_day = self._next_trading_day(observed_date)
            resolution = self._calendar.holiday_resolution(observed_date.year)
        except Exception as exc:
            return MarketCalendarSnapshot(
                observed_date=observed_date,
                status=MarketCalendarStatus.UNKNOWN,
                is_trading_day=None,
                is_holiday=None,
                previous_trading_day=None,
                next_trading_day=None,
                is_new_week_start=None,
                is_week_end=None,
                is_expiry_day=None,
                source="UNKNOWN",
                source_status=f"UNKNOWN:{type(exc).__name__}",
            )

        is_new_week = previous.isocalendar().week != observed_date.isocalendar().week
        is_week_end = next_day.isocalendar().week != observed_date.isocalendar().week
        source_status = getattr(resolution, "status", "AVAILABLE")
        source = getattr(resolution, "source", "ProductionTradingCalendar")
        return MarketCalendarSnapshot(
            observed_date=observed_date,
            status=MarketCalendarStatus.AVAILABLE,
            is_trading_day=is_trading,
            is_holiday=not is_trading and observed_date.weekday() < 5,
            previous_trading_day=previous,
            next_trading_day=next_day,
            is_new_week_start=is_new_week,
            is_week_end=is_week_end,
            is_expiry_day=expiry is not None and expiry == observed_date,
            source=source,
            source_status=str(source_status),
        )

    def _next_trading_day(self, value: date) -> date:
        current = value + timedelta(days=1)
        for _ in range(370):
            if self._calendar.is_trading_day(current):
                return current
            current += timedelta(days=1)
        raise RuntimeError("MARKET_CALENDAR_NEXT_TRADING_DAY_UNAVAILABLE")

    # Compatibility surface: consumers can migrate without owning calendar logic.
    def is_trading_day(self, value: date) -> bool:
        return self.snapshot(value).is_trading_day is True

    def prev_trading_day(self, value: date) -> date:
        snapshot = self.snapshot(value)
        if snapshot.previous_trading_day is None:
            raise ValueError("MARKET_CALENDAR_PREVIOUS_TRADING_DAY_UNAVAILABLE")
        return snapshot.previous_trading_day
