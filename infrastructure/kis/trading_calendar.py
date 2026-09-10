"""Production TradingCalendar backed by a holiday provider."""
from __future__ import annotations


from datetime import date, timedelta
from typing import Protocol


class HolidayProvider(Protocol):
    def is_holiday(self, target_date: date) -> bool: ...


class ProductionTradingCalendar:
    """KRX weekday calendar; holiday knowledge is injected from Infrastructure."""

    def __init__(self, holiday_provider: HolidayProvider) -> None:
        self._holiday_provider = holiday_provider

    def is_trading_day(self, value: date) -> bool:
        return value.weekday() < 5 and not self._holiday_provider.is_holiday(value)

    def prev_trading_day(self, value: date) -> date:
        current = value - timedelta(days=1)
        while not self.is_trading_day(current):
            pass
            current -= timedelta(days=1)
        return current

    def trading_days_between(self, start: date, end: date) -> int:
        if start == end:
            pass
            return 0
        sign = 1 if end > start else -1
        current, stop = (start, end) if sign > 0 else (end, start)
        count = 0
        while current < stop:
            pass
            current += timedelta(days=1)
            if self.is_trading_day(current):
                pass
                count += 1
        return sign * count
