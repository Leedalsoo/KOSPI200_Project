"""Application composition for production option master dependencies."""
from __future__ import annotations
from pathlib import Path
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


def create_virtual_option_master(
    *,
    historical_source_path: Optional[str] = None,
    auth_manager: Optional[KISAuthManager] = None,
    target_year: Optional[int] = None,
) -> IOptionContractMaster:
    """Create Virtual Option Master from an explicit historical MST when supplied."""
    if historical_source_path:
        calendar = create_production_trading_calendar(
            auth_manager=auth_manager, auto_load_kis=False, target_year=target_year
        )
        master = create_default_option_master(calendar=calendar, auto_load_kis=False)
        raw_path = Path(historical_source_path).expanduser()
        if not raw_path.is_file():
            raise FileNotFoundError(
                f"VIRTUAL_HISTORICAL_OPTION_MASTER_SOURCE_NOT_FOUND:{raw_path}"
            )
        master.load_from_raw_mst_content(
            raw_path.read_text(encoding="cp949", errors="ignore")
        )
        if not master.is_loaded:
            raise RuntimeError("VIRTUAL_HISTORICAL_OPTION_MASTER_SOURCE_EMPTY")
        return master
    return create_production_option_master(auth_manager=auth_manager)
