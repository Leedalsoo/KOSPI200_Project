# -*- coding: utf-8 -*-
"""Option Contract Master & KIS contract identity registry.

Preserves the legacy expiry lookup while additively retaining authoritative
KIS short/standard-code identity metadata from one raw MST parse boundary.
Calendar behavior is supplied through the standard TradingCalendar contract.
"""
import io
import logging
import re
import urllib.request
import zipfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Dict, Optional

from contracts.trading_calendar import TradingCalendar

logger = logging.getLogger(__name__)
KIS_FO_IDX_MASTER_URL = "https://new.real.download.dws.co.kr/common/master/fo_idx_code_mts.mst.zip"


class KisMasterSourceError(Exception):
    pass


class KisMasterDownloadError(KisMasterSourceError):
    pass


class KisMasterParseError(KisMasterSourceError):
    pass


@dataclass(frozen=True)
class KisOptionContractIdentity:
    shrn_iscd: str
    stnd_iscd: Optional[str]
    expiry: str
    option_type: Optional[str]
    strike: Optional[Decimal]
    info_type: Optional[str] = None


@dataclass(frozen=True)
class KisOptionMasterParseResult:
    legacy_contracts: Dict[str, str]
    identities: Dict[str, KisOptionContractIdentity]


KIS_INFO_TYPE_TO_OPTION_TYPE = {
    "5": "CALL", "D": "CALL", "L": "CALL",
    "6": "PUT", "E": "PUT", "M": "PUT",
}
_OPTION_INFO_TYPES = {"5", "6", "D", "E", "L", "M", "N", "O", "P", "Q", "R", "S"}
_MONTH_PATTERN = re.compile(r"20\d{4}")
_WEEKLY_PATTERN = re.compile(r"(\d{2})(\d{2})W(\d)")


def _require_calendar(calendar: Optional[TradingCalendar]) -> TradingCalendar:
    if calendar is None:
        raise KisMasterParseError(
            "TradingCalendar injection is required; no production calendar source "
            "is owned by OptionContractMaster."
        )
    return calendar


def calculate_krx_monthly_option_expiry(
    year: int, month: int, calendar: TradingCalendar
) -> str:
    first_day = date(year, month, 1)
    first_thursday = 1 + (3 - first_day.weekday()) % 7
    target_date = date(year, month, first_thursday + 7)
    while not calendar.is_trading_day(target_date):
        target_date = calendar.prev_trading_day(target_date)
    return target_date.strftime("%Y-%m-%d")


def calculate_krx_weekly_option_expiry(
    year: int, month: int, week_num: int, calendar: TradingCalendar
) -> str:
    first_day = date(year, month, 1)
    first_thursday = 1 + (3 - first_day.weekday()) % 7
    target_day = first_thursday + (week_num - 1) * 7
    max_days = (date(year, month + 1, 1) - timedelta(days=1)).day if month < 12 else 31
    target_date = date(year, month, min(target_day, max_days))
    while not calendar.is_trading_day(target_date):
        target_date = calendar.prev_trading_day(target_date)
    return target_date.strftime("%Y-%m-%d")


def _is_option_record(prod_type: str, symbol: str, name: str) -> bool:
    return (
        prod_type in _OPTION_INFO_TYPES
        or symbol.startswith(("2", "3", "B", "C"))
        or " C " in name or " P " in name
        or "Call" in name or "Put" in name
    )


def _calculate_expiry(
    symbol: str, name: str, calendar: TradingCalendar
) -> Optional[str]:
    weekly_m = _WEEKLY_PATTERN.search(name) or _WEEKLY_PATTERN.search(symbol)
    if weekly_m:
        try:
            return calculate_krx_weekly_option_expiry(
                2000 + int(weekly_m.group(1)),
                int(weekly_m.group(2)),
                int(weekly_m.group(3)),
                calendar,
            )
        except Exception as exc:
            logger.debug("Weekly option parse note (%s): %s", name, exc)
    month_m = _MONTH_PATTERN.search(name)
    if month_m:
        try:
            ym = month_m.group(0)
            year, month = int(ym[:4]), int(ym[4:6])
            if 1 <= month <= 12:
                return calculate_krx_monthly_option_expiry(year, month, calendar)
        except Exception as exc:
            logger.debug("Monthly option parse note (%s): %s", name, exc)
    return None


def _parse_strike(raw_acpr: str) -> Optional[Decimal]:
    raw_acpr = raw_acpr.strip()
    if not raw_acpr:
        return None
    try:
        value = Decimal(raw_acpr)
    except (InvalidOperation, ValueError):
        return None
    return value if value > 0 else None


def parse_kis_fo_idx_mst_result(
    raw_content: str, calendar: TradingCalendar
) -> KisOptionMasterParseResult:
    if not raw_content or not raw_content.strip():
        return KisOptionMasterParseResult({}, {})
    legacy: Dict[str, str] = {}
    identities: Dict[str, KisOptionContractIdentity] = {}

    for line in raw_content.splitlines():
        if not line or "|" not in line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 4:
            continue
        prod_type, symbol, standard_code, name = parts[:4]
        if not _is_option_record(prod_type, symbol, name):
            continue
        expiry = _calculate_expiry(symbol, name, calendar)
        if not symbol or not expiry:
            continue

        legacy[symbol] = expiry
        if standard_code:
            legacy[standard_code] = expiry

        strike = _parse_strike(parts[5]) if len(parts) >= 6 else None
        identity = KisOptionContractIdentity(
            shrn_iscd=symbol,
            stnd_iscd=standard_code or None,
            expiry=expiry,
            option_type=KIS_INFO_TYPE_TO_OPTION_TYPE.get(prod_type),
            strike=strike,
            info_type=prod_type or None,
        )
        existing = identities.get(symbol)
        if existing is not None and existing != identity:
            raise KisMasterParseError(
                f"Conflicting KIS identity for shrn_iscd '{symbol}'."
            )
        identities[symbol] = identity

    return KisOptionMasterParseResult(legacy, identities)


def parse_kis_fo_idx_mst(
    raw_content: str, calendar: TradingCalendar
) -> Dict[str, str]:
    return parse_kis_fo_idx_mst_result(raw_content, calendar).legacy_contracts


class KisOptionMasterLoader:
    @staticmethod
    def extract_raw_text_from_zip_bytes(zip_bytes: bytes) -> str:
        if not zip_bytes:
            raise KisMasterParseError(
                "Empty zip bytes provided for KIS master loading."
            )
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
                names = archive.namelist()
                target = next(
                    (
                        name for name in names
                        if "fo_idx_code_mts" in name
                        or "fo_idx_code" in name
                        or "optcode" in name
                    ),
                    None,
                )
                target = target or (names[0] if names else None)
                if not target:
                    raise KisMasterParseError(
                        "No valid master file found in zip archive."
                    )
                return archive.read(target).decode("cp949", errors="ignore")
        except KisMasterParseError:
            raise
        except Exception as exc:
            raise KisMasterParseError(
                f"Failed to extract zip archive: {exc}"
            ) from exc

    @classmethod
    def parse_raw_content(
        cls, raw_text: str, calendar: TradingCalendar
    ) -> KisOptionMasterParseResult:
        result = parse_kis_fo_idx_mst_result(raw_text, calendar)
        if not result.legacy_contracts:
            raise KisMasterParseError("Master file parsed 0 contracts.")
        return result

    @classmethod
    def load_result_from_zip_bytes(
        cls, zip_bytes: bytes, calendar: TradingCalendar
    ) -> KisOptionMasterParseResult:
        return cls.parse_raw_content(
            cls.extract_raw_text_from_zip_bytes(zip_bytes), calendar
        )

    @classmethod
    def load_from_zip_bytes(
        cls, zip_bytes: bytes, calendar: TradingCalendar
    ) -> Dict[str, str]:
        return cls.load_result_from_zip_bytes(
            zip_bytes, calendar
        ).legacy_contracts

    @classmethod
    def load_result_from_url(
        cls,
        url: str = KIS_FO_IDX_MASTER_URL,
        timeout: float = 10.0,
        calendar: Optional[TradingCalendar] = None,
    ) -> KisOptionMasterParseResult:
        cal = _require_calendar(calendar)
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return cls.load_result_from_zip_bytes(response.read(), cal)
        except KisMasterParseError:
            raise
        except Exception as exc:
            raise KisMasterDownloadError(
                f"Failed to download KIS master from {url}: {exc}"
            ) from exc

    @classmethod
    def load_from_url(
        cls,
        url: str = KIS_FO_IDX_MASTER_URL,
        timeout: float = 10.0,
        calendar: Optional[TradingCalendar] = None,
    ) -> Dict[str, str]:
        return cls.load_result_from_url(
            url, timeout, calendar
        ).legacy_contracts


class IOptionContractMaster(ABC):
    @abstractmethod
    def get_expiry(self, symbol: str) -> Optional[str]:
        pass

    @abstractmethod
    def register_contract(self, symbol: str, expiry: str) -> None:
        pass

    def get_contract_identity(
        self, shrn_iscd: str
    ) -> Optional[KisOptionContractIdentity]:
        return None

    def find_contract_identity(
        self, expiry: str, option_type: str, strike: Decimal
    ) -> Optional[KisOptionContractIdentity]:
        """Resolve one option contract by its economic identity."""
        return None


    def register_contract_identity(
        self, identity: KisOptionContractIdentity
    ) -> None:
        raise NotImplementedError(
            "This OptionContractMaster does not support identity registration."
        )

    @property
    def is_loaded(self) -> bool:
        return self.total_contracts > 0

    @property
    @abstractmethod
    def total_contracts(self) -> int:
        pass

    @property
    def last_error(self) -> Optional[str]:
        return None


class _IdentityOptionContractMaster(IOptionContractMaster):
    def _init_identity_registry(self) -> None:
        self._contract_identities: Dict[
            str, KisOptionContractIdentity
        ] = {}

    def get_contract_identity(
        self, shrn_iscd: str
    ) -> Optional[KisOptionContractIdentity]:
        return self._contract_identities.get(
            shrn_iscd.strip()
        ) if shrn_iscd else None

    def find_contract_identity(
        self, expiry: str, option_type: str, strike: Decimal
    ) -> Optional[KisOptionContractIdentity]:
        target_expiry = str(expiry).replace("-", "")[:6]
        target_type = str(option_type).upper()
        target_strike = Decimal(str(strike))
        for identity in self._contract_identities.values():
            if (
                identity.expiry.replace("-", "")[:6] == target_expiry
                and identity.option_type == target_type
                and identity.strike == target_strike
            ):
                return identity
        return None

    def register_contract_identity(
        self, identity: KisOptionContractIdentity
    ) -> None:
        key = identity.shrn_iscd.strip()
        if not key:
            raise KisMasterParseError(
                "KIS identity requires non-empty shrn_iscd."
            )
        existing = self._contract_identities.get(key)
        if existing is not None and existing != identity:
            raise KisMasterParseError(
                f"Conflicting registered KIS identity for shrn_iscd '{key}'."
            )
        self._contract_identities[key] = identity
        self.register_contract(key, identity.expiry)
        if identity.stnd_iscd:
            self.register_contract(identity.stnd_iscd, identity.expiry)

    def _apply_parse_result(self, result: KisOptionMasterParseResult) -> None:
        self._contracts.update(result.legacy_contracts)
        for identity in result.identities.values():
            self.register_contract_identity(identity)


class InMemoryOptionContractMaster(_IdentityOptionContractMaster):
    def __init__(
        self,
        contracts: Optional[Dict[str, str]] = None,
        auto_load_kis_source: bool = False,
        calendar: Optional[TradingCalendar] = None,
    ) -> None:
        self._contracts: Dict[str, str] = dict(contracts or {})
        self._init_identity_registry()
        self._last_error: Optional[str] = None
        if auto_load_kis_source and not self._contracts:
            self.load_from_kis_source(calendar=calendar)

    def get_expiry(self, symbol: str) -> Optional[str]:
        return self._contracts.get(symbol.strip()) if symbol else None

    def register_contract(self, symbol: str, expiry: str) -> None:
        if symbol and expiry:
            self._contracts[symbol.strip()] = expiry.strip()

    def load_from_kis_source(
        self,
        calendar: Optional[TradingCalendar] = None,
        url: str = KIS_FO_IDX_MASTER_URL,
    ) -> int:
        try:
            result = KisOptionMasterLoader.load_result_from_url(
                url=url, calendar=calendar
            )
            self._apply_parse_result(result)
            self._last_error = None
            return len(result.legacy_contracts)
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning(
                "[InMemoryOptionContractMaster] KIS source load note: %s", exc
            )
            return 0

    def load_from_raw_mst_content(
        self, raw_text: str, calendar: TradingCalendar
    ) -> int:
        result = KisOptionMasterLoader.parse_raw_content(raw_text, calendar)
        self._apply_parse_result(result)
        self._last_error = None
        return len(result.legacy_contracts)

    @property
    def total_contracts(self) -> int:
        return len(self._contracts)

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error


class KisProductionOptionContractMaster(_IdentityOptionContractMaster):
    def __init__(
        self,
        contracts: Optional[Dict[str, str]] = None,
        calendar: Optional[TradingCalendar] = None,
        auto_load: bool = True,
        url: str = KIS_FO_IDX_MASTER_URL,
    ) -> None:
        self.calendar = _require_calendar(calendar)
        self._contracts: Dict[str, str] = dict(contracts or {})
        self._init_identity_registry()
        self._last_error: Optional[str] = None
        if auto_load and not self._contracts:
            self.load_from_kis_source(url=url)

    def get_expiry(self, symbol: str) -> Optional[str]:
        return self._contracts.get(symbol.strip()) if symbol else None

    def register_contract(self, symbol: str, expiry: str) -> None:
        if symbol and expiry:
            self._contracts[symbol.strip()] = expiry.strip()

    def load_from_kis_source(self, url: str = KIS_FO_IDX_MASTER_URL) -> int:
        try:
            result = KisOptionMasterLoader.load_result_from_url(
                url=url, calendar=self.calendar
            )
            self._apply_parse_result(result)
            self._last_error = None
            return len(result.legacy_contracts)
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning(
                "[KisProductionOptionContractMaster] Source download note: %s",
                exc,
            )
            return 0

    def load_from_raw_mst_content(self, raw_text: str) -> int:
        try:
            result = KisOptionMasterLoader.parse_raw_content(
                raw_text, self.calendar
            )
            self._apply_parse_result(result)
            self._last_error = None
            return len(result.legacy_contracts)
        except Exception as exc:
            self._last_error = str(exc)
            raise

    def load_from_zip_bytes(self, zip_bytes: bytes) -> int:
        try:
            result = KisOptionMasterLoader.load_result_from_zip_bytes(
                zip_bytes, self.calendar
            )
            self._apply_parse_result(result)
            self._last_error = None
            return len(result.legacy_contracts)
        except Exception as exc:
            self._last_error = str(exc)
            raise

    @property
    def total_contracts(self) -> int:
        return len(self._contracts)

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error


def create_default_option_master(
    calendar: Optional[TradingCalendar] = None,
    contracts: Optional[Dict[str, str]] = None,
    auto_load_kis: bool = True,
) -> IOptionContractMaster:
    return KisProductionOptionContractMaster(
        contracts=contracts,
        calendar=calendar,
        auto_load=auto_load_kis,
    )
