"""Year-aware KIS-first holiday resolution. KRX caches are historical reference only."""
from __future__ import annotations
from contracts.trading_date import format_trading_date, parse_trading_date

import hashlib
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Optional, Set

from infrastructure.kis.holiday_provider import KISHolidayUnavailableError


KRX_HOLIDAY_SOURCE_URL = (
    "https://global.krx.co.kr/contents/GLB/05/0501/0501110000/"
    "GLB0501110000.jsp"
)
KRX_HOLIDAY_OTP_PATH = "/contents/COM/GenerateOTP.jspx"
KRX_HOLIDAY_DATA_PATH = "/contents/GLB/99/GLB99000001.jspx"
KRX_HOLIDAY_FORM_BLD = "/GLB/05/0501/0501110000/glb0501110000_01"
APPROVED_HOLIDAY_SCHEMA = "user-approved-holiday-list-v1"


def fetch_krx_holidays(year: int, *, urlopen=urllib.request.urlopen) -> Set[date]:
    """Legacy historical/reference-only loader; never used for runtime decisions."""
    otp_query = urllib.parse.urlencode({"name": "form", "bld": KRX_HOLIDAY_FORM_BLD}).encode("utf-8")
    otp_request = urllib.request.Request(
        "https://global.krx.co.kr" + KRX_HOLIDAY_OTP_PATH,
        data=otp_query, headers={"User-Agent": "Project200/holiday-calendar"}, method="POST"
    )
    with urlopen(otp_request, timeout=10) as response:
        otp = response.read().decode("utf-8").strip()
    if not otp:
        raise HolidayCalendarUnavailableError("KRX holiday OTP is empty")
    payload = urllib.parse.urlencode({"search_bas_yy": str(year), "gridTp": "KRX", "code": otp}).encode("utf-8")
    data_request = urllib.request.Request(
        "https://global.krx.co.kr" + KRX_HOLIDAY_DATA_PATH,
        data=payload, headers={"User-Agent": "Project200/holiday-calendar"}, method="POST"
    )
    with urlopen(data_request, timeout=10) as response:
        data = json.loads(response.read().decode("utf-8"))
    rows = data.get("block1")
    if not isinstance(rows, list):
        raise HolidayCalendarUnavailableError(f"KRX holiday response missing block1 for {year}")
    holidays: Set[date] = set()
    for row in rows:
        raw = str(row.get("calnd_dd") or row.get("calnd_dd_dy") or "").strip()
        try:
            parsed = parse_trading_date(raw)
        except ValueError:
            continue
        if parsed.year == year:
            holidays.add(parsed)
    if not holidays:
        raise HolidayCalendarUnavailableError(f"KRX holiday response empty for {year}")
    return holidays


class HolidayResolutionStatus(str, Enum):
    KIS = "KIS"
    APPROVED_LIST = "APPROVED_LIST"
    # Retained for historical result compatibility; not returned by the KIS-only resolver.
    KRX = "KRX"
    CACHE = "CACHE"
    UNKNOWN = "UNKNOWN"


class HolidayCalendarUnavailableError(RuntimeError):
    """Raised when a validated, complete KIS/approved holiday calendar is unavailable."""


@dataclass(frozen=True)
class HolidayResolution:
    year: int
    holidays: frozenset[date]
    status: HolidayResolutionStatus
    source: str


class KRXHolidayProvider:
    """Legacy KRX source/cache holder; retained for historical comparison only."""

    def __init__(
        self,
        *,
        cache_dir: Path,
        source_loader: Optional[Callable[[int], Set[date]]] = None,
    ) -> None:
        self._cache_dir = Path(cache_dir)
        self._source_loader = source_loader or fetch_krx_holidays
        self._last_error: Optional[str] = None

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def load_from_krx(self, year: int) -> Set[date]:
        raise HolidayCalendarUnavailableError("KRX_IS_NON_AUTHORITATIVE_FOR_RUNTIME")

    def load_from_cache(self, year: int) -> Set[date]:
        raise HolidayCalendarUnavailableError("KRX_CACHE_IS_NON_AUTHORITATIVE_FOR_RUNTIME")

    def _cache_path(self, year: int) -> Path:
        return self._cache_dir / "krx" / f"{year}.json"


class ApprovedHolidayListProvider:
    """Reads only an explicitly user-approved, hash-verified append-only calendar."""

    def __init__(self, directory: Path = Path("data/reference/kis/approved_holidays")) -> None:
        self.directory = Path(directory)

    @staticmethod
    def _holidays_hash(values: list[str]) -> str:
        canonical = "\n".join(sorted(values)).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def load_from_approved_list(self, year: int) -> tuple[Set[date], str]:
        candidates = []
        if not self.directory.is_dir():
            raise HolidayCalendarUnavailableError(f"APPROVED_HOLIDAY_LIST_NOT_FOUND:{year}")
        for path in self.directory.glob(f"holidays_{year}_*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if payload.get("schema_version") != APPROVED_HOLIDAY_SCHEMA:
                    continue
                if payload.get("year") != year or payload.get("approval_state") != "USER_APPROVED":
                    continue
                if not payload.get("approved_at_utc") or not payload.get("approval_reference"):
                    continue
                source_reference = str(payload.get("source_reference") or "").strip()
                checked_at = str(payload.get("checked_at_utc") or "").strip()
                raw_values = payload.get("holidays")
                if not source_reference or not checked_at or not isinstance(raw_values, list) or not raw_values:
                    continue
                values = sorted({date.fromisoformat(str(item)).isoformat() for item in raw_values})
                if any(date.fromisoformat(item).year != year for item in values):
                    continue
                if payload.get("holidays_sha256") != self._holidays_hash(values):
                    continue
                approved_at = datetime.fromisoformat(str(payload["approved_at_utc"]))
                if approved_at.tzinfo is None:
                    continue
                candidates.append((approved_at.astimezone(timezone.utc), set(parse_trading_date(v) for v in values), str(path)))
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                continue
        if not candidates:
            raise HolidayCalendarUnavailableError(f"APPROVED_HOLIDAY_LIST_NOT_FOUND_OR_INVALID:{year}")
        candidates.sort(key=lambda item: item[0], reverse=True)
        if len(candidates) > 1 and candidates[0][0] == candidates[1][0] and candidates[0][1] != candidates[1][1]:
            raise HolidayCalendarUnavailableError(f"APPROVED_HOLIDAY_LIST_APPROVAL_CONFLICT:{year}")
        _, holidays, source = candidates[0]
        return holidays, source


class FallbackHolidayProvider:
    """KIS complete annual calendar -> user-approved list -> UNKNOWN.

    The legacy KRX provider argument is accepted for constructor compatibility but is never called.
    """

    def __init__(
        self,
        *,
        kis_provider,
        krx_provider: KRXHolidayProvider | None = None,
        approved_list_provider: ApprovedHolidayListProvider | None = None,
        enable_kis: bool = True,
    ) -> None:
        self._kis_provider = kis_provider
        self._krx_provider = krx_provider
        self._approved_list_provider = approved_list_provider or ApprovedHolidayListProvider()
        self._enable_kis = enable_kis
        self._resolutions: dict[int, HolidayResolution] = {}

    @property
    def source_status(self) -> dict[int, HolidayResolutionStatus]:
        return {year: value.status for year, value in self._resolutions.items()}

    def get_resolution(self, year: int) -> HolidayResolution:
        cached = self._resolutions.get(year)
        if cached is not None:
            return cached

        if self._enable_kis:
            try:
                self._kis_provider.load_from_kis_api(year)
                if not self._kis_provider.is_year_loaded(year):
                    raise HolidayCalendarUnavailableError(
                        f"KIS holiday data not loaded for {year}: {getattr(self._kis_provider, 'last_error', None)}"
                    )
                is_complete = getattr(self._kis_provider, "is_year_complete", None)
                if callable(is_complete) and not is_complete(year):
                    raise HolidayCalendarUnavailableError(
                        f"KIS annual holiday coverage incomplete for {year}"
                    )
                holidays = self._kis_provider.get_holidays_for_year(year)
                if not holidays:
                    raise HolidayCalendarUnavailableError(f"KIS holiday list empty for {year}")
                return self._remember(year, holidays, HolidayResolutionStatus.KIS, "KIS:CTCA0903R")
            except Exception:
                pass

        try:
            holidays, source = self._approved_list_provider.load_from_approved_list(year)
            return self._remember(year, holidays, HolidayResolutionStatus.APPROVED_LIST, source)
        except Exception:
            resolution = HolidayResolution(
                year=year, holidays=frozenset(), status=HolidayResolutionStatus.UNKNOWN, source="UNKNOWN"
            )
            self._resolutions[year] = resolution
            return resolution

    def get_holidays_for_year(self, year: int) -> Set[date]:
        resolution = self.get_resolution(year)
        if resolution.status is HolidayResolutionStatus.UNKNOWN:
            raise HolidayCalendarUnavailableError(f"holiday calendar UNKNOWN for {year}")
        return set(resolution.holidays)

    def is_holiday(self, target_date: date) -> bool:
        return target_date in self.get_holidays_for_year(target_date.year)

    def _remember(
        self,
        year: int,
        holidays: Set[date],
        status: HolidayResolutionStatus,
        source: str,
    ) -> HolidayResolution:
        resolution = HolidayResolution(
            year=year, holidays=frozenset(holidays), status=status, source=source
        )
        self._resolutions[year] = resolution
        return resolution
