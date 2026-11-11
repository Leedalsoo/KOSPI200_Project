"""KIS official product specifications for KOSPI200 option contracts.

Source: https://m.koreainvestment.com/main/bond/domestic/_static/TF03bd010100.jsp
The source defines the standard/mini multipliers, monthly expiry rule and premium tick sizes.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Protocol

KIS_OPTION_PRODUCT_SPEC_URL = (
    "https://m.koreainvestment.com/main/bond/domestic/_static/TF03bd010100.jsp"
)
KIS_MONTHLY_OPTION_EXPIRY_SOURCE = (
    "KIS_OFFICIAL_PRODUCT_SPEC:MONTHLY_SECOND_THURSDAY"
)
KIS_MONTHLY_OPTION_EXPIRY_RULE_ID = "KIS_PRODUCT_GUIDE_MONTHLY_OPTION_EXPIRY"
KIS_KOSPI200_OPTION_CONTRACT_MULTIPLIER = Decimal("250000")
KIS_MINI_KOSPI200_OPTION_CONTRACT_MULTIPLIER = Decimal("50000")


class TradingCalendarPort(Protocol):
    def is_trading_day(self, value: date) -> bool: ...
    def prev_trading_day(self, value: date) -> date: ...


def calculate_kis_monthly_option_expiry(
    month_label: str, calendar: TradingCalendarPort
) -> str:
    """Resolve the KIS monthly option's second-Thursday expiry.

    KIS specifies the second Thursday of the settlement month, advanced to the
    preceding trading day when that Thursday is a holiday.
    """
    if not re.fullmatch(r"20\d{4}", str(month_label or "")):
        raise ValueError("KIS_MONTHLY_OPTION_MONTH_LABEL_INVALID")
    year, month = int(month_label[:4]), int(month_label[4:6])
    if month < 1 or month > 12:
        raise ValueError("KIS_MONTHLY_OPTION_MONTH_LABEL_INVALID")
    first = date(year, month, 1)
    first_thursday_offset = (3 - first.weekday()) % 7
    second_thursday = first + timedelta(days=first_thursday_offset + 7)
    if calendar.is_trading_day(second_thursday):
        expiry = second_thursday
    else:
        expiry = calendar.prev_trading_day(second_thursday)
        if expiry >= second_thursday or not calendar.is_trading_day(expiry):
            raise ValueError("KIS_MONTHLY_OPTION_EXPIRY_CALENDAR_INVALID")
    if expiry.month != month or expiry.year != year:
        raise ValueError("KIS_MONTHLY_OPTION_EXPIRY_OUTSIDE_SETTLEMENT_MONTH")
    return expiry.strftime("%Y%m%d")


def kis_option_contract_multiplier(instrument_family: str) -> Decimal:
    family = str(instrument_family or "").strip().upper()
    if family == "STANDARD":
        return KIS_KOSPI200_OPTION_CONTRACT_MULTIPLIER
    if family == "MINI":
        return KIS_MINI_KOSPI200_OPTION_CONTRACT_MULTIPLIER
    raise ValueError("KIS_OPTION_INSTRUMENT_FAMILY_UNSUPPORTED")


def kis_option_price_tick(premium: Decimal | str | int | float) -> Decimal:
    value = Decimal(str(premium))
    if value < 0:
        raise ValueError("KIS_OPTION_PREMIUM_INVALID")
    return Decimal("0.01") if value < Decimal("10") else Decimal("0.05")
