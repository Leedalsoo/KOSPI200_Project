"""Application composition for production option master dependencies."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.option.option_master import IOptionContractMaster, create_default_option_master
from infrastructure.kis.auth import KISAuthManager
from infrastructure.kis.trading_calendar_factory import create_kis_trading_calendar
from infrastructure.kis.kis_index_option_master_source import get_kis_index_master_snapshot
from infrastructure.kis.kis_option_expiry_source import KISOptionExpiryResolver
from infrastructure.kis.trading_calendar import ProductionTradingCalendar


def create_production_trading_calendar(
    *,
    auth_manager: Optional[KISAuthManager] = None,
    auto_load_kis: bool = True,
    strict_mode: bool = False,
    target_year: Optional[int] = None,
    krx_source_loader=None,
    calendar_cache_dir: Optional[str] = None,
) -> ProductionTradingCalendar:
    auth = auth_manager or KISAuthManager.from_env()
    return create_kis_trading_calendar(
        auth_manager=auth,
        daily_auth_manager=auth,
        is_vts=bool(getattr(auth, "is_vts", True)),
        auto_load_kis=auto_load_kis,
        strict_mode=strict_mode,
        target_year=target_year,
        approved_holiday_dir=Path("data/reference/kis/approved_holidays"),
    )


def create_production_option_master(
    *,
    auth_manager: Optional[KISAuthManager] = None,
    auto_load_calendar: bool = True,
    auto_load_kis_master: bool = True,
    strict_calendar: bool = False,
    target_year: Optional[int] = None,
) -> IOptionContractMaster:
    auth = auth_manager or KISAuthManager.from_env()
    calendar = create_production_trading_calendar(
        auth_manager=auth,
        auto_load_kis=auto_load_calendar,
        strict_mode=strict_calendar,
        target_year=target_year,
    )
    resolver_cache = {}

    def resolve_expiry(symbol: str, master_sha256: str):
        resolver = resolver_cache.get(master_sha256)
        if resolver is None:
            resolver = KISOptionExpiryResolver(
                master_sha256=master_sha256,
                auth_manager=auth,
                environment="VTS" if getattr(auth, "is_vts", True) else "LIVE",
            )
            resolver_cache[master_sha256] = resolver
        return resolver.resolve(symbol)

    return create_default_option_master(
        calendar=calendar,
        auto_load_kis=auto_load_kis_master,
        master_source_loader=get_kis_index_master_snapshot,
        expiry_resolver=resolve_expiry,
    )


def create_virtual_option_master(
    *,
    historical_source_path: Optional[str] = None,
    auth_manager: Optional[KISAuthManager] = None,
    target_year: Optional[int] = None,
    krx_source_loader=None,
    calendar_cache_dir: Optional[str] = None,
) -> IOptionContractMaster:
    """Create Virtual Option Master from an explicit historical MST."""
    if historical_source_path:
        calendar = create_production_trading_calendar(
            auth_manager=auth_manager,
            auto_load_kis=False,
            target_year=target_year,
            krx_source_loader=krx_source_loader,
            calendar_cache_dir=calendar_cache_dir,
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
