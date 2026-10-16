"""Shared KIS production trading-calendar composition boundary."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from infrastructure.kis.auth import KISAuthManager
from infrastructure.kis.daily_trading_day_provider import KISDailyTradingDayProvider
from infrastructure.kis.holiday_fallback_provider import (
    ApprovedHolidayListProvider,
    FallbackHolidayProvider,
)
from infrastructure.kis.holiday_provider import KISHolidayProvider
from infrastructure.kis.trading_calendar import ProductionTradingCalendar


def create_kis_trading_calendar(
    *,
    auth_manager: Optional[KISAuthManager] = None,
    daily_auth_manager: Optional[KISAuthManager] = None,
    is_vts: bool = True,
    auto_load_kis: bool = True,
    strict_mode: bool = False,
    target_year: int | None = None,
    approved_holiday_dir: str | Path = "data/reference/kis/approved_holidays",
    daily_evidence_dir: str | Path | None = None,
) -> ProductionTradingCalendar:
    """Compose one calendar for all strategies and collectors.

    Annual resolution accepts only a complete KIS calendar or an explicitly
    user-approved, hash-verified list. No non-KIS runtime fallback is wired.
    Daily responses positively confirm only listed dates; absence is unknown.
    """
    annual_auth = auth_manager or KISAuthManager.from_env(is_vts=is_vts)
    rolling_auth = daily_auth_manager or annual_auth
    annual_provider = KISHolidayProvider(
        auth_manager=annual_auth,
        auto_load=False,
        strict_mode=strict_mode,
        target_year=target_year,
    )
    annual_resolution = FallbackHolidayProvider(
        kis_provider=annual_provider,
        approved_list_provider=ApprovedHolidayListProvider(
            directory=Path(approved_holiday_dir)
        ),
        enable_kis=auto_load_kis,
    )
    daily_provider = None
    if auto_load_kis:
        daily_kwargs = {"auth_manager": rolling_auth}
        if daily_evidence_dir is not None:
            daily_kwargs["evidence_dir"] = Path(daily_evidence_dir)
        daily_provider = KISDailyTradingDayProvider(**daily_kwargs)
    return ProductionTradingCalendar(
        annual_resolution,
        daily_trading_day_provider=daily_provider,
    )
