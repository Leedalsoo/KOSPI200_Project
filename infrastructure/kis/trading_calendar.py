"""Production TradingCalendar backed by KIS daily dates and annual holiday data."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional, Protocol


class HolidayProvider(Protocol):
    def is_holiday(self, target_date: date) -> bool: ...


class DailyTradingDayProvider(Protocol):
    def is_confirmed_trading_day(self, target_date: date) -> Optional[bool]: ...


class ProductionTradingCalendar:
    """KIS-confirmed rolling dates take precedence; unknown dates require annual resolution."""

    def __init__(
        self,
        holiday_provider: HolidayProvider,
        daily_trading_day_provider: Optional[DailyTradingDayProvider] = None,
    ) -> None:
        self._holiday_provider = holiday_provider
        self._daily_trading_day_provider = daily_trading_day_provider

    def is_trading_day(self, value: date) -> bool:
        if value.weekday() >= 5:
            return False
        if self._daily_trading_day_provider is not None:
            try:
                confirmed = self._daily_trading_day_provider.is_confirmed_trading_day(value)
            except Exception:
                # A daily endpoint failure is not proof of a holiday/open day.
                # The annual KIS/approved-calendar resolver must still decide.
                confirmed = None
            if confirmed is True:
                return True
        # If the rolling KIS response does not list the date, the annual
        # authoritative calendar must resolve it. Unknown must raise/block.
        return not self._holiday_provider.is_holiday(value)

    def prev_trading_day(self, value: date) -> date:
        current = value - timedelta(days=1)
        while not self.is_trading_day(current):
            current -= timedelta(days=1)
        return current

    def holiday_resolution(self, year: int):
        resolver = getattr(self._holiday_provider, "get_resolution", None)
        if not callable(resolver):
            return type("CalendarResolution", (), {"status": "AVAILABLE", "source": "HolidayProvider"})()
        return resolver(year)

    def trading_days_between(self, start: date, end: date) -> int:
        if start == end:
            return 0
        sign = 1 if end > start else -1
        current, stop = (start, end) if sign > 0 else (end, start)
        count = 0
        while current < stop:
            current += timedelta(days=1)
            if self.is_trading_day(current):
                count += 1
        return sign * count
