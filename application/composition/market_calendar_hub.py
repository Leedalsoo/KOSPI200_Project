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
            resolver = getattr(self._calendar, "holiday_resolution", None)
            resolution = resolver(observed_date.year) if callable(resolver) else None
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
    def resolve_option_expiry(self, tick: Any, option_master: Any | None = None) -> date | None:
        master = option_master or self._calendar
        if master is None or not hasattr(master, "find_contract_identity"):
            return None
        identity = master.find_contract_identity(
            str(getattr(tick, "expiry", "")),
            str(getattr(tick, "option_type", "")),
            getattr(tick, "strike_price", None),
        )
        if identity is None or not getattr(identity, "expiry", None):
            return None
        try:
            return date.fromisoformat(str(identity.expiry))
        except ValueError as exc:
            raise ValueError("MARKET_CALENDAR_AUTHORITATIVE_OPTION_EXPIRY_INVALID") from exc

    def flags(self, observed_date: date, expiry: date | None = None) -> tuple[bool, bool, bool]:
        snapshot = self.snapshot(observed_date, expiry=expiry)
        if not snapshot.available:
            raise ValueError("MARKET_CALENDAR_SNAPSHOT_UNAVAILABLE")
        return (
            snapshot.is_new_week_start is True,
            snapshot.is_expiry_day is True,
            snapshot.is_week_end is True,
        )

    def is_trading_day(self, value: date) -> bool:
        return self.snapshot(value).is_trading_day is True

    def prev_trading_day(self, value: date) -> date:
        snapshot = self.snapshot(value)
        if snapshot.previous_trading_day is None:
            raise ValueError("MARKET_CALENDAR_PREVIOUS_TRADING_DAY_UNAVAILABLE")
        return snapshot.previous_trading_day
