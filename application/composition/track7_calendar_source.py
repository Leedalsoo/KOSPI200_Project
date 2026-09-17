from __future__ import annotations

from datetime import date, timedelta
from typing import Any


class Track7CalendarSource:
    """Project Track7 calendar facts from the composed TradingCalendar."""

    def __init__(self, calendar: Any, option_master: Any | None = None) -> None:
        if calendar is None:
            raise ValueError("TRACK7_TRADING_CALENDAR_REQUIRED")
        self.calendar = calendar
        self.option_master = option_master

    def resolve_option_expiry(self, tick: Any) -> date | None:
        if self.option_master is None:
            return None
        identity = self.option_master.find_contract_identity(
            str(getattr(tick, "expiry", "")),
            str(getattr(tick, "option_type", "")),
            getattr(tick, "strike_price", None),
        )
        if identity is None or not identity.expiry:
            return None
        try:
            return date.fromisoformat(str(identity.expiry))
        except ValueError as exc:
            raise ValueError("TRACK7_AUTHORITATIVE_OPTION_EXPIRY_INVALID") from exc

    def _require_trading_day(self, value: date) -> None:
        if not self.calendar.is_trading_day(value):
            raise ValueError("TRACK7_CALENDAR_DATE_NOT_TRADING_DAY")

    def is_new_week_start(self, value: date) -> bool:
        self._require_trading_day(value)
        previous = self.calendar.prev_trading_day(value)
        return previous.isocalendar().week != value.isocalendar().week

    def is_week_end(self, value: date) -> bool:
        self._require_trading_day(value)
        candidate = value
        for _ in range(7):
            candidate += timedelta(days=1)
            if self.calendar.is_trading_day(candidate):
                return candidate.isocalendar().week != value.isocalendar().week
        raise ValueError("TRACK7_NEXT_TRADING_DAY_UNAVAILABLE")

    def flags(self, observed: date, expiry: date | None) -> tuple[bool, bool, bool]:
        self._require_trading_day(observed)
        return (
            self.is_new_week_start(observed),
            expiry is not None and expiry == observed,
            self.is_week_end(observed),
        )
