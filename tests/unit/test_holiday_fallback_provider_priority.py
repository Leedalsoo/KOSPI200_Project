import json
from datetime import date
from pathlib import Path

from infrastructure.kis.holiday_fallback_provider import (
    FallbackHolidayProvider,
    HolidayResolutionStatus,
    KRX_HOLIDAY_SOURCE_URL,
    KRXHolidayProvider,
)

YEAR = 2026
KRX_HOLIDAY = date(YEAR, 1, 1)
KIS_HOLIDAY = date(YEAR, 2, 1)


class StubKISProvider:
    def __init__(self, holidays=None, error=None):
        self.holidays = set(holidays or ())
        self.error = error
        self.calls = 0
        self.loaded = False

    def load_from_kis_api(self, year):
        self.calls += 1
        if self.error:
            raise RuntimeError(self.error)
        self.loaded = True

    def is_year_loaded(self, year):
        return self.loaded

    def get_holidays_for_year(self, year):
        return set(self.holidays)


def make_cache(cache_dir: Path, holidays):
    path = cache_dir / "krx" / f"{YEAR}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "year": YEAR,
        "source": "KRX",
        "source_url": KRX_HOLIDAY_SOURCE_URL,
        "fetched_at": "2026-01-01T00:00:00+00:00",
        "holidays": sorted(day.isoformat() for day in holidays),
    }), encoding="utf-8")


def test_krx_official_source_is_primary_and_skips_kis(tmp_path):
    kis = StubKISProvider(holidays={KIS_HOLIDAY})
    krx = KRXHolidayProvider(cache_dir=tmp_path, source_loader=lambda year: {KRX_HOLIDAY})
    resolution = FallbackHolidayProvider(kis_provider=kis, krx_provider=krx).get_resolution(YEAR)
    assert resolution.status is HolidayResolutionStatus.KRX
    assert resolution.holidays == frozenset({KRX_HOLIDAY})
    assert kis.calls == 0
    assert (tmp_path / "krx" / f"{YEAR}.json").is_file()


def test_kis_is_used_only_after_krx_source_failure(tmp_path):
    kis = StubKISProvider(holidays={KIS_HOLIDAY})
    krx = KRXHolidayProvider(cache_dir=tmp_path, source_loader=lambda year: (_ for _ in ()).throw(RuntimeError("KRX offline")))
    resolution = FallbackHolidayProvider(kis_provider=kis, krx_provider=krx).get_resolution(YEAR)
    assert resolution.status is HolidayResolutionStatus.KIS
    assert resolution.holidays == frozenset({KIS_HOLIDAY})
    assert kis.calls == 1


def test_cache_is_used_after_krx_and_kis_fail(tmp_path):
    make_cache(tmp_path, {KRX_HOLIDAY})
    kis = StubKISProvider(error="KIS unavailable")
    krx = KRXHolidayProvider(cache_dir=tmp_path, source_loader=lambda year: (_ for _ in ()).throw(RuntimeError("KRX offline")))
    resolution = FallbackHolidayProvider(kis_provider=kis, krx_provider=krx).get_resolution(YEAR)
    assert resolution.status is HolidayResolutionStatus.CACHE
    assert resolution.holidays == frozenset({KRX_HOLIDAY})
    assert kis.calls == 1


def test_unknown_is_fail_closed_after_all_sources_fail(tmp_path):
    kis = StubKISProvider(error="KIS unavailable")
    krx = KRXHolidayProvider(cache_dir=tmp_path, source_loader=lambda year: (_ for _ in ()).throw(RuntimeError("KRX offline")))
    resolution = FallbackHolidayProvider(kis_provider=kis, krx_provider=krx).get_resolution(YEAR)
    assert resolution.status is HolidayResolutionStatus.UNKNOWN
    assert not resolution.holidays
    assert kis.calls == 1
