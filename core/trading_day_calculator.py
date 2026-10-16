from __future__ import annotations
from contracts.trading_date import format_trading_date

from datetime import date, time, timedelta
from zoneinfo import ZoneInfo
from typing import Any

from contracts.option_expiry import CanonicalOptionExpiryError, require_exact_option_expiry


class TradingDayCalculationError(RuntimeError):
    pass


class KISTradingDayCalculator:
    """D-4 and DTE calculations that require KIS expiry provenance and a validated calendar."""

    def __init__(self, calendar: Any) -> None:
        self.calendar = calendar

    @staticmethod
    def _expiry_date(expiry_record: Any) -> date:
        source = str(getattr(expiry_record, "source", "") or "")
        endpoint = str(getattr(expiry_record, "endpoint", "") or "")
        tr_id = str(getattr(expiry_record, "tr_id", "") or "")
        response_hash = str(getattr(expiry_record, "raw_response_sha256", "") or "")
        field_name = str(getattr(expiry_record, "response_field", "") or "")
        status = getattr(expiry_record, "http_status", None)
        rt_cd = str(getattr(expiry_record, "rt_cd", "") or "")
        raw_expiry = str(getattr(expiry_record, "expiry_yyyymmdd", "") or "")
        if (
            source != "KIS_REST:futs_last_tr_date"
            or not endpoint.endswith("/inquire-price")
            or not tr_id
            or field_name != "output1.futs_last_tr_date"
            or status != 200
            or rt_cd != "0"
            or len(response_hash) != 64
        ):
            raise TradingDayCalculationError("KIS_EXACT_EXPIRY_PROVENANCE_REQUIRED")
        try:
            exact = require_exact_option_expiry(raw_expiry)
            return date(int(exact[:4]), int(exact[4:6]), int(exact[6:8]))
        except (CanonicalOptionExpiryError, ValueError) as exc:
            raise TradingDayCalculationError("KIS_EXACT_EXPIRY_INVALID") from exc

    def _require_calendar_source(self, year: int) -> None:
        resolver = getattr(self.calendar, "holiday_resolution", None)
        if not callable(resolver):
            raise TradingDayCalculationError("TRADING_CALENDAR_PROVENANCE_REQUIRED")
        try:
            resolution = resolver(year)
        except Exception as exc:
            raise TradingDayCalculationError(f"TRADING_CALENDAR_UNAVAILABLE:{year}") from exc
        status = getattr(resolution, "status", None)
        status = getattr(status, "value", status)
        if str(status) not in {"KIS", "APPROVED_LIST"}:
            raise TradingDayCalculationError(f"TRADING_CALENDAR_UNKNOWN:{year}")
        if not getattr(resolution, "source", None):
            raise TradingDayCalculationError(f"TRADING_CALENDAR_SOURCE_REQUIRED:{year}")

    def _is_trading_day(self, value: date) -> bool:
        self._require_calendar_source(value.year)
        try:
            result = self.calendar.is_trading_day(value)
        except Exception as exc:
            raise TradingDayCalculationError(f"TRADING_DAY_LOOKUP_FAILED:{format_trading_date(value)}") from exc
        if not isinstance(result, bool):
            raise TradingDayCalculationError(f"TRADING_DAY_RESULT_UNKNOWN:{format_trading_date(value)}")
        return result

    def d4_date(self, expiry_record: Any) -> date:
        expiry = self._expiry_date(expiry_record)
        if not self._is_trading_day(expiry):
            raise TradingDayCalculationError("KIS_EXPIRY_IS_NOT_CONFIRMED_TRADING_DAY")
        cursor = expiry
        counted = 0
        for _ in range(366):
            try:
                previous = self.calendar.prev_trading_day(cursor)
            except Exception as exc:
                raise TradingDayCalculationError(f"PREVIOUS_TRADING_DAY_UNAVAILABLE:{format_trading_date(cursor)}") from exc
            if not isinstance(previous, date) or previous >= cursor:
                raise TradingDayCalculationError("PREVIOUS_TRADING_DAY_INVALID")
            if not self._is_trading_day(previous):
                raise TradingDayCalculationError(f"PREVIOUS_TRADING_DAY_NOT_CONFIRMED:{format_trading_date(previous)}")
            cursor = previous
            counted += 1
            if counted == 4:
                return cursor
        raise TradingDayCalculationError("D4_TRADING_DAY_SEARCH_LIMIT_EXCEEDED")

    def d4_exit_due(self, now: Any, expiry_record: Any) -> bool:
        """Return true at/after 11:00 KST on D-4, or on a later date."""
        if not hasattr(now, "tzinfo") or now.tzinfo is None or now.utcoffset() is None:
            raise TradingDayCalculationError("CURRENT_TIMEZONE_AWARE_REQUIRED")
        current_kst = now.astimezone(ZoneInfo("Asia/Seoul"))
        boundary = self.d4_date(expiry_record)
        if current_kst.date() > boundary:
            return True
        if current_kst.date() < boundary:
            return False
        return current_kst.timetz().replace(tzinfo=None) >= time(11, 0)
    def trading_sessions_to_expiry(self, as_of: date, expiry_record: Any) -> int:
        expiry = self._expiry_date(expiry_record)
        if as_of > expiry:
            raise TradingDayCalculationError("AS_OF_AFTER_EXPIRY")
        if not self._is_trading_day(as_of):
            raise TradingDayCalculationError("AS_OF_NOT_CONFIRMED_TRADING_DAY")
        if not self._is_trading_day(expiry):
            raise TradingDayCalculationError("KIS_EXPIRY_IS_NOT_CONFIRMED_TRADING_DAY")
        cursor = as_of
        sessions = 0
        while cursor < expiry:
            cursor += timedelta(days=1)
            if self._is_trading_day(cursor):
                sessions += 1
        return sessions

    def dte10_entry_allowed(self, as_of: date, expiry_record: Any) -> bool:
        return self.trading_sessions_to_expiry(as_of, expiry_record) >= 10
