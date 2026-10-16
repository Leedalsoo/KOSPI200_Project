from __future__ import annotations
from contracts.trading_date import parse_trading_date

from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from typing import Mapping, Sequence


KST = timezone(timedelta(hours=9))
OPTION_TRADE_TR_ID = "H0IOCNT0"
FUTURES_TRADE_TR_ID = "H0IFCNT0"
FUTURES_QUOTE_TR_ID = "H0IFASP0"
MAX_SUBSCRIPTIONS = 41

# The strategies currently require offsets from ATM through ±15 points.
STRATEGY_MONTHLY_OFFSETS = (
    Decimal("-15.0"),
    Decimal("-12.5"),
    Decimal("-10.0"),
    Decimal("-7.5"),
    Decimal("-5.0"),
    Decimal("-2.5"),
    Decimal("0.0"),
    Decimal("2.5"),
    Decimal("5.0"),
    Decimal("7.5"),
    Decimal("10.0"),
    Decimal("12.5"),
    Decimal("15.0"),
)


@dataclass(frozen=True)
class CollectionWindow:
    start: date
    end: date


@dataclass(frozen=True)
class CollectionPlan:
    subscriptions: tuple[tuple[str, str], ...]
    monthly_contract_label: str
    weekly_contract_label: str
    monthly_strikes: tuple[Decimal, ...]
    weekly_strikes: tuple[Decimal, ...]
    standard_futures_symbol: str
    mini_futures_symbol: str


def _row_month(row: Mapping[str, object]) -> str:
    month = str(row.get("month") or "")
    if len(month) != 6 or not month.isdigit():
        raise ValueError("KIS_OPTION_MASTER_MONTH_LABEL_REQUIRED")
    return month


def _row_week(row: Mapping[str, object]) -> int:
    label = str(row.get("week_label") or "")
    if len(label) != 2 or label[0] != "W" or not label[1].isdigit():
        raise ValueError("KIS_OPTION_MASTER_WEEK_LABEL_REQUIRED")
    return int(label[1])


def _select_monthly_rows(rows: Sequence[Mapping[str, object]], as_of: date) -> tuple[str, tuple[Mapping[str, object], ...]]:
    current_month = f"{as_of.year:04d}{as_of.month:02d}"
    months = sorted({
        _row_month(row) for row in rows
        if row.get("product_series") == "MONTHLY"
        and row.get("instrument_family") == "STANDARD"
        and row.get("type_code") in {"5", "6"}
        and _row_month(row) >= current_month
    })
    if not months:
        raise ValueError(f"KIS_MONTHLY_OPTION_MONTH_REQUIRED:{current_month}")
    month = months[0]
    selected = tuple(
        row for row in rows
        if row.get("product_series") == "MONTHLY"
        and row.get("instrument_family") == "STANDARD"
        and row.get("type_code") in {"5", "6"}
        and _row_month(row) == month
    )
    if not selected:
        raise ValueError(f"KIS_MONTHLY_OPTION_ROWS_REQUIRED:{month}")
    return month, selected


def _select_weekly_rows(rows: Sequence[Mapping[str, object]], as_of: date) -> tuple[str, tuple[Mapping[str, object], ...]]:
    current_month = f"{as_of.year:04d}{as_of.month:02d}"
    current_week = (as_of.day - 1) // 7 + 1
    candidates: list[tuple[str, int, str]] = []
    for row in rows:
        series = str(row.get("product_series") or "")
        if series not in {"THURSDAY_WEEKLY", "MONDAY_WEEKLY"} or row.get("instrument_family") != "STANDARD":
            continue
        month = _row_month(row)
        if month < current_month:
            continue
        week = _row_week(row)
        if month == current_month and week < current_week:
            continue
        if month == current_month and (
            (series == "MONDAY_WEEKLY" and as_of.weekday() > 0)
            or (series == "THURSDAY_WEEKLY" and as_of.weekday() > 3)
        ):
            continue
        candidates.append((month, week, series))
    if not candidates:
        raise ValueError(f"KIS_WEEKLY_OPTION_SERIES_REQUIRED:{as_of.isoformat()}")
    month, week, series = min(candidates)
    label = f"{month[2:]}W{week}:{series}"
    selected = tuple(
        row for row in rows
        if row.get("product_series") == series
        and row.get("instrument_family") == "STANDARD"
        and _row_month(row) == month
        and _row_week(row) == week
    )
    if not selected:
        raise ValueError(f"KIS_WEEKLY_OPTION_ROWS_REQUIRED:{label}")
    return label, selected


def _find_option_symbol(rows: Sequence[Mapping[str, object]], *, option_type: str, strike: Decimal) -> str:
    matches = [
        row for row in rows
        if row.get("option_type") == option_type
        and row.get("strike") == strike
        and isinstance(row.get("short_code"), str)
        and row.get("short_code")
    ]
    if len(matches) != 1:
        raise ValueError(f"KIS_AUTHORITATIVE_OPTION_SYMBOL_REQUIRED:{option_type}:{strike}:{len(matches)}")
    return str(matches[0]["short_code"])


def build_collection_plan(
    *,
    reference_price: Decimal,
    option_master_rows: Sequence[Mapping[str, object]],
    standard_futures_symbol: str,
    mini_futures_symbol: str,
    as_of: date,
) -> CollectionPlan:
    if not option_master_rows:
        raise ValueError("KIS_OPTION_MASTER_ROWS_REQUIRED")
    monthly_label, monthly_rows = _select_monthly_rows(option_master_rows, as_of)
    weekly_label, weekly_rows = _select_weekly_rows(option_master_rows, as_of)
    available_monthly_strikes = sorted({
        row["strike"] for row in monthly_rows if isinstance(row.get("strike"), Decimal)
    })
    if not available_monthly_strikes:
        raise ValueError(f"KIS_MONTHLY_OPTION_STRIKES_REQUIRED:{monthly_label}")
    atm = min(available_monthly_strikes, key=lambda strike: abs(strike - Decimal(reference_price)))
    monthly_strikes = tuple(atm + offset for offset in STRATEGY_MONTHLY_OFFSETS)
    weekly_strikes = (atm - Decimal("15.0"), atm + Decimal("15.0"))
    subscriptions: list[tuple[str, str]] = []
    for strike in monthly_strikes:
        for option_type in ("PUT", "CALL"):
            subscriptions.append((OPTION_TRADE_TR_ID, _find_option_symbol(monthly_rows, option_type=option_type, strike=strike)))
    for strike in weekly_strikes:
        for option_type in ("PUT", "CALL"):
            subscriptions.append((OPTION_TRADE_TR_ID, _find_option_symbol(weekly_rows, option_type=option_type, strike=strike)))
    subscriptions.extend((
        (FUTURES_TRADE_TR_ID, standard_futures_symbol),
        (FUTURES_QUOTE_TR_ID, standard_futures_symbol),
        (FUTURES_TRADE_TR_ID, mini_futures_symbol),
        (FUTURES_QUOTE_TR_ID, mini_futures_symbol),
    ))
    if len(subscriptions) > MAX_SUBSCRIPTIONS:
        raise ValueError(f"KIS_WEBSOCKET_SUBSCRIPTION_LIMIT_EXCEEDED:{len(subscriptions)}")
    return CollectionPlan(
        subscriptions=tuple(subscriptions),
        monthly_contract_label=monthly_label,
        weekly_contract_label=weekly_label,
        monthly_strikes=monthly_strikes,
        weekly_strikes=weekly_strikes,
        standard_futures_symbol=standard_futures_symbol,
        mini_futures_symbol=mini_futures_symbol,
    )


def is_collection_day(day: date, window: CollectionWindow) -> bool:
    return window.start <= day <= window.end and day.weekday() < 5


def should_stop(now_iso: str, window: CollectionWindow) -> bool:
    now = datetime.fromisoformat(now_iso)
    if now.tzinfo is None:
        raise ValueError("STOP_CLOCK_MUST_BE_TIMEZONE_AWARE")
    return now.astimezone(KST).date() > window.end or (
        now.astimezone(KST).date() == window.end
        and now.astimezone(KST).time().isoformat() >= "23:59:59"
    )
