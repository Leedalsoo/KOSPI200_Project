"""Canonical YYYYMMDD date-only format helpers. Timestamps remain ISO 8601."""
from __future__ import annotations

from datetime import date, datetime


def format_trading_date(value: date) -> str:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise TypeError("TRADING_DATE_MUST_BE_DATE_ONLY")
    return value.strftime("%Y%m%d")


def parse_trading_date(value: str | date) -> date:
    if isinstance(value, datetime):
        raise TypeError("TRADING_DATE_MUST_BE_DATE_ONLY")
    if isinstance(value, date):
        return value
    raw = str(value).strip().replace("/", "-")
    if len(raw) == 8 and raw.isdigit():
        return datetime.strptime(raw, "%Y%m%d").date()
    return date.fromisoformat(raw)
