from datetime import date
from typing import Protocol


class TradingCalendar(Protocol):
    """Minimal trading-day capability required by OptionContractMaster."""

    def is_trading_day(self, value: date) -> bool: ...

    def prev_trading_day(self, value: date) -> date: ...

    def trading_days_between(self, start: date, end: date) -> int: ...
