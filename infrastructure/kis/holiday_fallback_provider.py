"""Year-aware KRX -> KIS -> cache holiday fallback infrastructure.

The fallback is fail-closed: UNKNOWN never becomes a weekday/trading day.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Optional, Set


KRX_HOLIDAY_SOURCE_URL = (
    "https://global.krx.co.kr/contents/GLB/05/0501/0501110000/"
    "GLB0501110000.jsp"
)

KRX_HOLIDAY_OTP_PATH = "/contents/COM/GenerateOTP.jspx"
KRX_HOLIDAY_DATA_PATH = "/contents/GLB/99/GLB99000001.jspx"
KRX_HOLIDAY_FORM_BLD = "/GLB/05/0501/0501110000/glb0501110000_01"

def fetch_krx_holidays(year: int, *, urlopen=urllib.request.urlopen) -> Set[date]:
    """Fetch the official KRX yearly holiday list without hardcoded dates."""
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
            parsed = date.fromisoformat(raw)
        except ValueError:
            continue
        if parsed.year == year:
            holidays.add(parsed)
    if not holidays:
        raise HolidayCalendarUnavailableError(f"KRX holiday response empty for {year}")
    return holidays


class HolidayResolutionStatus(str, Enum):
    KIS = "KIS"
    KRX = "KRX"
    CACHE = "CACHE"
    UNKNOWN = "UNKNOWN"


class HolidayCalendarUnavailableError(RuntimeError):
    """Raised when an authoritative holiday decision cannot be obtained."""


@dataclass(frozen=True)
class HolidayResolution:
    year: int
    holidays: frozenset[date]
    status: HolidayResolutionStatus
    source: str


class KRXHolidayProvider:
    """Loads year-specific KRX holiday data and persists a local snapshot."""

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
        if self._source_loader is None:
            raise HolidayCalendarUnavailableError(
                "KRX authoritative machine-readable loader is not configured"
            )
        try:
            values = set(self._source_loader(year))
            self._validate_year(values, year)
            self._write_cache(year, values, source="KRX")
            self._last_error = None
            return values
        except Exception as exc:
            self._last_error = str(exc)
            raise HolidayCalendarUnavailableError(
                f"KRX holiday source unavailable for {year}: {exc}"
            ) from exc

    def load_from_cache(self, year: int) -> Set[date]:
        path = self._cache_path(year)
        if not path.is_file():
            raise HolidayCalendarUnavailableError(
                f"KRX holiday cache unavailable for {year}: {path}"
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("year") != year:
                raise ValueError("cache year mismatch")
            if payload.get("source") != "KRX":
                raise ValueError("cache source is not KRX")
            if payload.get("source_url") != KRX_HOLIDAY_SOURCE_URL:
                raise ValueError("cache source URL mismatch")
            values = {date.fromisoformat(v) for v in payload.get("holidays", [])}
            self._validate_year(values, year)
            self._last_error = None
            return values
        except Exception as exc:
            self._last_error = str(exc)
            raise HolidayCalendarUnavailableError(
                f"Invalid KRX holiday cache for {year}: {exc}"
            ) from exc

    def _cache_path(self, year: int) -> Path:
        return self._cache_dir / "krx" / f"{year}.json"

    def _write_cache(self, year: int, holidays: Set[date], *, source: str) -> None:
        path = self._cache_path(year)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "year": year,
            "source": source,
            "source_url": KRX_HOLIDAY_SOURCE_URL,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "holidays": sorted(v.isoformat() for v in holidays),
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _validate_year(values: Set[date], year: int) -> None:
        if not values:
            raise ValueError("holiday calendar is empty")
        if any(value.year != year for value in values):
            raise ValueError("holiday contains a different calendar year")


class FallbackHolidayProvider:
    """KRX authoritative -> KIS fallback -> KRX cache -> UNKNOWN."""

    def __init__(
        self,
        *,
        kis_provider,
        krx_provider: KRXHolidayProvider,
        enable_kis: bool = True,
    ) -> None:
        self._kis_provider = kis_provider
        self._krx_provider = krx_provider
        self._enable_kis = enable_kis
        self._resolutions: dict[int, HolidayResolution] = {}

    @property
    def source_status(self) -> dict[int, HolidayResolutionStatus]:
        return {year: value.status for year, value in self._resolutions.items()}

    def get_resolution(self, year: int) -> HolidayResolution:
        cached = self._resolutions.get(year)
        if cached is not None:
            return cached

        # KRX official source is primary; only fall back to KIS when it fails.
        try:
            holidays = self._krx_provider.load_from_krx(year)
            return self._remember(
                year, holidays, HolidayResolutionStatus.KRX, KRX_HOLIDAY_SOURCE_URL
            )
        except Exception:
            pass

        if self._enable_kis:
            try:
                self._kis_provider.load_from_kis_api(year)
                if not self._kis_provider.is_year_loaded(year):
                    raise HolidayCalendarUnavailableError(
                        f"KIS holiday calendar not loaded for {year}"
                    )
                holidays = self._kis_provider.get_holidays_for_year(year)
                return self._remember(
                    year, holidays, HolidayResolutionStatus.KIS, "KIS:" + str(year)
                )
            except Exception:
                pass

        try:
            holidays = self._krx_provider.load_from_cache(year)
            return self._remember(
                year,
                holidays,
                HolidayResolutionStatus.CACHE,
                str(self._krx_provider._cache_path(year)),
            )
        except Exception:
            resolution = HolidayResolution(
                year=year,
                holidays=frozenset(),
                status=HolidayResolutionStatus.UNKNOWN,
                source="UNKNOWN",
            )
            self._resolutions[year] = resolution
            return resolution

    def get_holidays_for_year(self, year: int) -> Set[date]:
        resolution = self.get_resolution(year)
        if resolution.status is HolidayResolutionStatus.UNKNOWN:
            raise HolidayCalendarUnavailableError(
                f"holiday calendar UNKNOWN for {year}"
            )
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
            year=year,
            holidays=frozenset(holidays),
            status=status,
            source=source,
        )
        self._resolutions[year] = resolution
        return resolution
