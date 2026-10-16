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
from typing import Callable, Dict, Mapping, Optional

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
    # Multiplier is intentionally unknown until a KIS-authoritative source is proven.
    contract_multiplier: Optional[Decimal] = None
    instrument_family: Optional[str] = None
    product_series: Optional[str] = None
    week_label: Optional[str] = None
    expiry_source: Optional[str] = None
    expiry_observed_at: Optional[str] = None
    expiry_endpoint: Optional[str] = None
    expiry_tr_id: Optional[str] = None
    expiry_response_sha256: Optional[str] = None
    expiry_master_sha256: Optional[str] = None
    master_sha256: Optional[str] = None

    def __post_init__(self) -> None:
        from contracts.option_expiry import CanonicalOptionExpiryError, require_exact_option_expiry
        try:
            exact = require_exact_option_expiry(self.expiry)
        except CanonicalOptionExpiryError as exc:
            raise ValueError("OPTION_EXPIRY_EXACT_DATE_REQUIRED") from exc
        object.__setattr__(self, "expiry", exact)
        for field_name in ("expiry_response_sha256", "expiry_master_sha256", "master_sha256"):
            value = getattr(self, field_name)
            if value is not None and not re.fullmatch(r"[0-9a-f]{64}", str(value)):
                raise ValueError(f"KIS_OPTION_IDENTITY_{field_name.upper()}_INVALID")


@dataclass(frozen=True)
class KisOptionMasterParseResult:
    legacy_contracts: Dict[str, str]
    identities: Dict[str, KisOptionContractIdentity]
    raw_content: Optional[str] = None
    master_sha256: Optional[str] = None


KIS_KOSPI200_OPTION_CONTRACT_MULTIPLIER = Decimal("250000")
KIS_MINI_KOSPI200_OPTION_CONTRACT_MULTIPLIER = Decimal("50000")

KIS_INFO_TYPE_TO_OPTION_TYPE = {
    "5": "CALL", "D": "CALL", "L": "CALL", "N": "CALL",
    "6": "PUT", "E": "PUT", "M": "PUT", "O": "PUT",
}
_OPTION_INFO_TYPES = {"5", "6", "D", "E", "L", "M", "N", "O"}
_MONTH_PATTERN = re.compile(r"(?<!\d)(20\d{4})(?:\d{2})?(?!\d)")
_WEEKLY_PATTERN = re.compile(r"(?<!\d)(\d{2})(\d{2})W([1-5])(?!\d)", re.IGNORECASE)


def _classify_kis_option_product(prod_type: str, name: str) -> Optional[dict[str, object]]:
    option_type = KIS_INFO_TYPE_TO_OPTION_TYPE.get(prod_type)
    if option_type is None:
        return None
    monthly = prod_type in {"5", "6", "D", "E"}
    if monthly:
        month_match = _MONTH_PATTERN.search(name)
        side_match = re.search(r"(C|P)\s+20\d{4}(?:\d{2})?(?:\s|$)", name)
        if not month_match or not side_match:
            return None
        if (side_match.group(1) == "C") != (option_type == "CALL"):
            return None
        return {
            "option_type": option_type,
            "product_series": "MONTHLY",
            "instrument_family": "MINI" if prod_type in {"D", "E"} else "STANDARD",
            "month": month_match.group(1),
            "week_label": None,
        }

    weekly_match = _WEEKLY_PATTERN.search(name)
    if not weekly_match:
        return None
    side_match = re.search(r"(C|P)\s+\d{4}W[1-5](?:\s|$)", name, re.IGNORECASE)
    if not side_match or (side_match.group(1).upper() == "C") != (option_type == "CALL"):
        return None
    monday_marker = bool(re.search(r"M\s+[CP]\s+\d{4}W[1-5]", name, re.IGNORECASE))
    if prod_type in {"N", "O"} and not monday_marker:
        return None
    if prod_type in {"L", "M"} and monday_marker:
        return None
    return {
        "option_type": option_type,
        "product_series": "MONDAY_WEEKLY" if prod_type in {"N", "O"} else "THURSDAY_WEEKLY",
        "instrument_family": "STANDARD",
        "month": f"20{weekly_match.group(1)}{weekly_match.group(2)}",
        "week_label": f"W{weekly_match.group(3)}",
    }


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
    """Legacy API fails closed because YYYYMM cannot identify an exact expiry."""
    raise KisMasterParseError("OPTION_EXPIRY_EXACT_DATE_REQUIRED")


def calculate_krx_weekly_option_expiry(
    year: int, month: int, week_num: int, calendar: TradingCalendar, *, weekday: int = 3
) -> str:
    """Legacy API fails closed because a weekly label is not an exact expiry."""
    raise KisMasterParseError("OPTION_EXPIRY_EXACT_DATE_REQUIRED")


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
    """Return only a source-supplied exact YYYYMMDD date; never infer from labels."""
    from contracts.option_expiry import CanonicalOptionExpiryError, require_exact_option_expiry

    for candidate in (name, symbol):
        match = re.search(r"(?<!\d)(20\d{6})(?!\d)", candidate or "")
        if match:
            try:
                return require_exact_option_expiry(match.group(1))
            except CanonicalOptionExpiryError:
                continue
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
    raw_content: str,
    calendar: TradingCalendar,
    *,
    expiry_records: Mapping[str, object] | None = None,
    master_sha256: str | None = None,
) -> KisOptionMasterParseResult:
    if not raw_content or not raw_content.strip():
        return KisOptionMasterParseResult({}, {}, raw_content, master_sha256)
    legacy: Dict[str, str] = {}
    identities: Dict[str, KisOptionContractIdentity] = {}
    expiry_records = expiry_records or {}

    for line in raw_content.splitlines():
        if not line or "|" not in line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 9 or parts[7] != "2001":
            continue
        prod_type, symbol, standard_code, name = parts[:4]
        product = _classify_kis_option_product(prod_type, name)
        if product is None or not symbol:
            continue

        expiry = _calculate_expiry(symbol, name, calendar)
        expiry_record = expiry_records.get(symbol)
        if expiry is None and expiry_record is not None:
            expiry = str(getattr(expiry_record, "expiry_yyyymmdd", "") or "")
            required_provenance = (
                "source", "received_at_utc", "endpoint", "tr_id",
                "raw_response_sha256", "master_sha256",
            )
            if not expiry or any(not getattr(expiry_record, key, None) for key in required_provenance):
                raise KisMasterParseError("KIS_OPTION_EXPIRY_PROVENANCE_REQUIRED")
        if not expiry:
            # YYYYMM / YYMMWn are labels, not exact expiry dates.
            continue
        from contracts.option_expiry import CanonicalOptionExpiryError, require_exact_option_expiry
        try:
            expiry = require_exact_option_expiry(expiry)
        except CanonicalOptionExpiryError as exc:
            raise KisMasterParseError("OPTION_EXPIRY_EXACT_DATE_REQUIRED") from exc
        if expiry_record is not None:
            recorded_expiry = require_exact_option_expiry(str(getattr(expiry_record, "expiry_yyyymmdd", "")))
            if recorded_expiry != expiry:
                raise KisMasterParseError("KIS_OPTION_EXPIRY_SOURCE_CONFLICT")

        legacy[symbol] = expiry
        if standard_code:
            legacy[standard_code] = expiry

        strike = _parse_strike(parts[5])
        identity = KisOptionContractIdentity(
            shrn_iscd=symbol,
            stnd_iscd=standard_code or None,
            expiry=expiry,
            option_type=str(product["option_type"]),
            strike=strike,
            info_type=prod_type or None,
            # No multiplier field exists in the observed KIS index-master row.
            # Do not promote hard-coded product values to authoritative data.
            contract_multiplier=None,
            instrument_family=str(product["instrument_family"]),
            product_series=str(product["product_series"]),
            week_label=str(product["week_label"]) if product["week_label"] is not None else None,
            expiry_source=(
                str(getattr(expiry_record, "source"))
                if expiry_record is not None
                else "KIS_OFFICIAL_INDEX_MASTER"
            ),
            expiry_observed_at=(
                str(getattr(expiry_record, "received_at_utc"))
                if expiry_record is not None
                else None
            ),
            expiry_endpoint=(
                str(getattr(expiry_record, "endpoint"))
                if expiry_record is not None
                else None
            ),
            expiry_tr_id=(
                str(getattr(expiry_record, "tr_id"))
                if expiry_record is not None
                else None
            ),
            expiry_response_sha256=(
                str(getattr(expiry_record, "raw_response_sha256"))
                if expiry_record is not None
                else None
            ),
            expiry_master_sha256=(
                str(getattr(expiry_record, "master_sha256"))
                if expiry_record is not None
                else None
            ),
            master_sha256=master_sha256,
        )
        existing = identities.get(symbol)
        if existing is not None and existing != identity:
            raise KisMasterParseError(
                f"Conflicting KIS identity for shrn_iscd '{symbol}'."
            )
        identities[symbol] = identity

    return KisOptionMasterParseResult(legacy, identities, raw_content, master_sha256)


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
        cls,
        raw_text: str,
        calendar: TradingCalendar,
        *,
        expiry_records: Mapping[str, object] | None = None,
        master_sha256: str | None = None,
        allow_unresolved: bool = False,
    ) -> KisOptionMasterParseResult:
        result = parse_kis_fo_idx_mst_result(
            raw_text, calendar, expiry_records=expiry_records, master_sha256=master_sha256
        )
        if not result.legacy_contracts and not allow_unresolved:
            raise KisMasterParseError("Master file parsed 0 exact-expiry contracts.")
        return result

    @classmethod
    def load_result_from_zip_bytes(
        cls,
        zip_bytes: bytes,
        calendar: TradingCalendar,
        *,
        expiry_records: Mapping[str, object] | None = None,
        allow_unresolved: bool = False,
    ) -> KisOptionMasterParseResult:
        from hashlib import sha256
        return cls.parse_raw_content(
            cls.extract_raw_text_from_zip_bytes(zip_bytes),
            calendar,
            expiry_records=expiry_records,
            master_sha256=sha256(zip_bytes).hexdigest(),
            allow_unresolved=allow_unresolved,
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
                payload = response.read()
            return cls.load_result_from_zip_bytes(payload, cal, allow_unresolved=True)
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


    def list_contract_identities(self, expiry: Optional[str] = None) -> tuple[KisOptionContractIdentity, ...]:
        """Return source-owned contract identities for authoritative selection."""
        return ()

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
        from contracts.option_expiry import CanonicalOptionExpiryError, require_exact_option_expiry
        try:
            target_expiry = require_exact_option_expiry(expiry)
        except CanonicalOptionExpiryError:
            return None
        target_type = str(option_type).upper()
        target_strike = Decimal(str(strike))
        matches = [
            identity for identity in self._contract_identities.values()
            if identity.expiry == target_expiry
            and identity.option_type == target_type
            and identity.strike == target_strike
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            standard_matches = [
                identity for identity in matches
                if identity.instrument_family == "STANDARD"
                or (
                    identity.instrument_family is None
                    and identity.contract_multiplier == KIS_KOSPI200_OPTION_CONTRACT_MULTIPLIER
                )
            ]
            return standard_matches[0] if len(standard_matches) == 1 else None
        return None

    def list_contract_identities(self, expiry: Optional[str] = None) -> tuple[KisOptionContractIdentity, ...]:
        if expiry is None:
            return tuple(self._contract_identities.values())
        from contracts.option_expiry import CanonicalOptionExpiryError, require_exact_option_expiry
        try:
            target = require_exact_option_expiry(expiry)
        except CanonicalOptionExpiryError:
            return ()
        return tuple(identity for identity in self._contract_identities.values() if identity.expiry == target)

    def register_contract_identity(
        self, identity: KisOptionContractIdentity
    ) -> None:
        from contracts.option_expiry import CanonicalOptionExpiryError, require_exact_option_expiry
        key = identity.shrn_iscd.strip()
        try:
            exact_expiry = require_exact_option_expiry(identity.expiry)
        except CanonicalOptionExpiryError as exc:
            raise KisMasterParseError("OPTION_EXPIRY_EXACT_DATE_REQUIRED") from exc
        if identity.expiry != exact_expiry:
            identity = KisOptionContractIdentity(
                shrn_iscd=identity.shrn_iscd, stnd_iscd=identity.stnd_iscd,
                expiry=exact_expiry, option_type=identity.option_type, strike=identity.strike,
                info_type=identity.info_type, contract_multiplier=identity.contract_multiplier,
                instrument_family=identity.instrument_family, product_series=identity.product_series,
                week_label=identity.week_label, expiry_source=identity.expiry_source,
                expiry_observed_at=identity.expiry_observed_at, expiry_endpoint=identity.expiry_endpoint,
                expiry_tr_id=identity.expiry_tr_id, expiry_response_sha256=identity.expiry_response_sha256,
                expiry_master_sha256=identity.expiry_master_sha256, master_sha256=identity.master_sha256,
            )
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
        self.calendar = calendar
        self._contracts: Dict[str, str] = {}
        for symbol, expiry in (contracts or {}).items():
            if symbol and expiry:
                self.register_contract(symbol, expiry)
        self._init_identity_registry()
        self._last_error: Optional[str] = None
        if auto_load_kis_source and not self._contracts:
            self.load_from_kis_source(calendar=calendar)

    def get_expiry(self, symbol: str) -> Optional[str]:
        return self._contracts.get(symbol.strip()) if symbol else None

    def register_contract(self, symbol: str, expiry: str) -> None:
        if symbol and expiry:
            from contracts.option_expiry import CanonicalOptionExpiryError, require_exact_option_expiry
            try:
                exact_expiry = require_exact_option_expiry(expiry)
            except CanonicalOptionExpiryError as exc:
                raise KisMasterParseError("OPTION_EXPIRY_EXACT_DATE_REQUIRED") from exc
            self._contracts[symbol.strip()] = exact_expiry

    def load_from_kis_source(
        self,
        calendar: Optional[TradingCalendar] = None,
        url: str = KIS_FO_IDX_MASTER_URL,
    ) -> int:
        try:
            result = KisOptionMasterLoader.load_result_from_url(url=url, calendar=calendar)
            self._apply_parse_result(result)
            self._last_error = None
            return len(result.legacy_contracts)
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("[InMemoryOptionContractMaster] KIS source load note: %s", exc)
            return 0

    def load_from_raw_mst_content(self, raw_text: str, calendar: TradingCalendar) -> int:
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
        master_source_loader: Callable[[], object] | None = None,
        expiry_resolver: Callable[[str, str], object] | None = None,
    ) -> None:
        self.calendar = _require_calendar(calendar)
        self._master_source_loader = master_source_loader
        self._expiry_resolver = expiry_resolver
        self._master_raw_content: str | None = None
        self._master_sha256: str | None = None
        self._known_master_rows: Dict[str, str] = {}
        self._contracts: Dict[str, str] = {}
        for symbol, expiry in (contracts or {}).items():
            if symbol and expiry:
                self.register_contract(symbol, expiry)
        self._init_identity_registry()
        self._last_error: Optional[str] = None
        if auto_load and not self._contracts:
            self.load_from_kis_source(url=url)

    def get_expiry(self, symbol: str) -> Optional[str]:
        if not symbol:
            return None
        clean = symbol.strip()
        existing = self._contracts.get(clean)
        if existing is not None:
            return existing
        identity = self.get_contract_identity(clean)
        return identity.expiry if identity is not None else None

    def get_contract_identity(self, shrn_iscd: str) -> Optional[KisOptionContractIdentity]:
        if not shrn_iscd:
            return None
        clean = shrn_iscd.strip()
        existing = super().get_contract_identity(clean)
        if existing is not None:
            return existing
        line = self._known_master_rows.get(clean)
        if line is None or self._expiry_resolver is None or not self._master_sha256:
            return None
        try:
            parts = [part.strip() for part in line.split("|")]
            short_code = parts[1]
            identity = super().get_contract_identity(short_code)
            if identity is None:
                record = self._expiry_resolver(short_code, self._master_sha256)
                result = parse_kis_fo_idx_mst_result(
                    line, self.calendar, expiry_records={short_code: record},
                    master_sha256=self._master_sha256,
                )
                identity = result.identities.get(short_code)
                if identity is None:
                    self._last_error = "KIS_OPTION_MASTER_IDENTITY_UNRESOLVED"
                    return None
                self._apply_parse_result(result)
                self._last_error = None
                identity = super().get_contract_identity(short_code)
            return identity
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("KIS exact expiry resolution blocked for %s: %s", clean, exc)
            return None

    def find_contract_identity(
        self, expiry: str, option_type: str, strike: Decimal
    ) -> Optional[KisOptionContractIdentity]:
        existing = super().find_contract_identity(expiry, option_type, strike)
        if existing is not None:
            return existing
        if not self._known_master_rows or self._expiry_resolver is None:
            return None
        from contracts.option_expiry import CanonicalOptionExpiryError, require_exact_option_expiry
        try:
            target = require_exact_option_expiry(expiry)
        except CanonicalOptionExpiryError:
            return None
        target_strike = Decimal(str(strike))
        candidates = []
        for line in self._known_master_rows.values():
            parts = [part.strip() for part in line.split("|")]
            if len(parts) < 9 or parts[7] != "2001":
                continue
            product = _classify_kis_option_product(parts[0], parts[3])
            if not product or product["option_type"] != str(option_type).upper():
                continue
            if product["month"] != target[:6] or _parse_strike(parts[5]) != target_strike:
                continue
            candidates.append(parts[1])
        for candidate in dict.fromkeys(candidates):
            self.get_contract_identity(candidate)
        return super().find_contract_identity(target, option_type, target_strike)

    def register_contract(self, symbol: str, expiry: str) -> None:
        if symbol and expiry:
            from contracts.option_expiry import CanonicalOptionExpiryError, require_exact_option_expiry
            try:
                exact_expiry = require_exact_option_expiry(expiry)
            except CanonicalOptionExpiryError as exc:
                raise KisMasterParseError("OPTION_EXPIRY_EXACT_DATE_REQUIRED") from exc
            self._contracts[symbol.strip()] = exact_expiry

    def load_from_kis_source(self, url: str = KIS_FO_IDX_MASTER_URL) -> int:
        try:
            if self._master_source_loader is not None:
                snapshot = self._master_source_loader()
                raw_content = str(getattr(snapshot, "raw_content", "") or "")
                master_sha256 = str(getattr(snapshot, "archive_sha256", "") or "")
                if not raw_content or not re.fullmatch(r"[0-9a-f]{64}", master_sha256):
                    raise KisMasterParseError("KIS_CACHED_MASTER_SNAPSHOT_INVALID")
                self._master_raw_content = raw_content
                self._master_sha256 = master_sha256
                self._known_master_rows = {}
                for line in raw_content.splitlines():
                    parts = [part.strip() for part in line.split("|")]
                    if len(parts) >= 9 and parts[7] == "2001" and _classify_kis_option_product(parts[0], parts[3]):
                        self._known_master_rows[parts[1]] = line
                        if parts[2]:
                            self._known_master_rows[parts[2]] = line
                result = parse_kis_fo_idx_mst_result(
                    raw_content, self.calendar, master_sha256=master_sha256
                )
            else:
                result = KisOptionMasterLoader.load_result_from_url(
                    url=url, calendar=self.calendar
                )
                self._master_raw_content = result.raw_content
                self._master_sha256 = result.master_sha256
                if self._master_raw_content:
                    for line in self._master_raw_content.splitlines():
                        parts = [part.strip() for part in line.split("|")]
                        if len(parts) >= 9 and parts[7] == "2001" and _classify_kis_option_product(parts[0], parts[3]):
                            self._known_master_rows[parts[1]] = line
                            if parts[2]:
                                self._known_master_rows[parts[2]] = line
            self._apply_parse_result(result)
            self._last_error = None
            return len(set(self._known_master_rows.values()))
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
    def is_loaded(self) -> bool:
        return bool(self._master_raw_content) or self.total_contracts > 0

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
    master_source_loader: Callable[[], object] | None = None,
    expiry_resolver: Callable[[str, str], object] | None = None,
) -> IOptionContractMaster:
    return KisProductionOptionContractMaster(
        contracts=contracts,
        calendar=calendar,
        auto_load=auto_load_kis,
        master_source_loader=master_source_loader,
        expiry_resolver=expiry_resolver,
    )
