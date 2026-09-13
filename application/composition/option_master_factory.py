"""Application composition for production option master dependencies."""
from __future__ import annotations
from typing import Optional

from core.option.option_master import IOptionContractMaster, create_default_option_master
from infrastructure.kis.auth import KISAuthManager
from infrastructure.kis.holiday_provider import KISHolidayProvider
from infrastructure.kis.trading_calendar import ProductionTradingCalendar


def create_production_trading_calendar(*, auth_manager: Optional[KISAuthManager] = None, auto_load_kis: bool = True, strict_mode: bool = False, target_year: Optional[int] = None) -> ProductionTradingCalendar:
    auth = auth_manager or KISAuthManager.from_env()
    provider = KISHolidayProvider(auth_manager=auth, auto_load=auto_load_kis, strict_mode=strict_mode, target_year=target_year)
    return ProductionTradingCalendar(provider)


def create_production_option_master(*, auth_manager: Optional[KISAuthManager] = None, auto_load_calendar: bool = True, auto_load_kis_master: bool = True, strict_calendar: bool = False, target_year: Optional[int] = None) -> IOptionContractMaster:
    calendar = create_production_trading_calendar(auth_manager=auth_manager, auto_load_kis=auto_load_calendar, strict_mode=strict_calendar, target_year=target_year)
    return create_default_option_master(calendar=calendar, auto_load_kis=auto_load_kis_master)
