from datetime import date
import pytest

from infrastructure.kis.holiday_fallback_provider import (
    FallbackHolidayProvider,
    HolidayCalendarUnavailableError,
    HolidayResolutionStatus,
    KRXHolidayProvider,
    fetch_krx_holidays,
)
from infrastructure.kis.trading_calendar import ProductionTradingCalendar


class FakeKIS:
    def __init__(self, holidays=None, fail=False):
        self.holidays = set(holidays or [])
        self.fail = fail

    def load_from_kis_api(self, year):
        if self.fail:
            raise RuntimeError("KIS unavailable")
        return len([v for v in self.holidays if v.year == year])

    def get_holidays_for_year(self, year):
        return {v for v in self.holidays if v.year == year}

    def is_year_loaded(self, year):
        return not self.fail and any(v.year == year for v in self.holidays)

    def is_holiday(self, value):
        return value in self.holidays


def test_krx_remote_loader_parses_official_payload():
    class Response:
        def __init__(self, payload):
            self.payload = payload.encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return self.payload

    responses = [
        Response("OTP123"),
        Response('{"block1":[{"calnd_dd":"2027-01-01"},{"calnd_dd":"2027-09-24"}]}'),
    ]

    def urlopen(request, timeout=10):
        return responses.pop(0)

    assert fetch_krx_holidays(2027, urlopen=urlopen) == {
        date(2027, 1, 1),
        date(2027, 9, 24),
    }


def test_kis_primary_is_year_aware(tmp_path):
    kis = FakeKIS({date(2026, 9, 24), date(2027, 9, 24)})
    krx = KRXHolidayProvider(cache_dir=tmp_path)
    provider = FallbackHolidayProvider(kis_provider=kis, krx_provider=krx)

    assert provider.get_resolution(2026).status is HolidayResolutionStatus.KIS
    assert provider.is_holiday(date(2026, 9, 24))
    assert provider.get_resolution(2027).status is HolidayResolutionStatus.KIS
    assert provider.is_holiday(date(2027, 9, 24))


def test_kis_failure_falls_back_to_krx_and_caches_each_year(tmp_path):
    kis = FakeKIS(fail=True)
    calls = []

    def loader(year):
        calls.append(year)
        return {date(year, 9, 24), date(year, 9, 25)}

    krx = KRXHolidayProvider(cache_dir=tmp_path, source_loader=loader)
    provider = FallbackHolidayProvider(kis_provider=kis, krx_provider=krx)

    resolution = provider.get_resolution(2026)
    assert resolution.status is HolidayResolutionStatus.KRX
    assert provider.is_holiday(date(2026, 9, 25))
    assert calls == [2026]
    assert (tmp_path / "krx" / "2026.json").is_file()


def _krx_unavailable(year):
    raise RuntimeError("KRX unavailable")


def test_cached_snapshot_is_used_when_kis_and_krx_are_unavailable(tmp_path):
    krx = KRXHolidayProvider(cache_dir=tmp_path, source_loader=_krx_unavailable)
    krx._write_cache(2027, {date(2027, 10, 3)}, source="KRX")
    provider = FallbackHolidayProvider(
        kis_provider=FakeKIS(fail=True),
        krx_provider=krx,
    )

    resolution = provider.get_resolution(2027)
    assert resolution.status is HolidayResolutionStatus.CACHE
    assert provider.is_holiday(date(2027, 10, 3))


def test_all_sources_failed_are_unknown_and_fail_closed(tmp_path):
    provider = FallbackHolidayProvider(
        kis_provider=FakeKIS(fail=True),
        krx_provider=KRXHolidayProvider(cache_dir=tmp_path, source_loader=_krx_unavailable),
    )

    resolution = provider.get_resolution(2028)
    assert resolution.status is HolidayResolutionStatus.UNKNOWN

    with pytest.raises(HolidayCalendarUnavailableError):
        provider.is_holiday(date(2028, 1, 4))


def test_trading_calendar_does_not_treat_unknown_as_trading_day(tmp_path):
    provider = FallbackHolidayProvider(
        kis_provider=FakeKIS(fail=True),
        krx_provider=KRXHolidayProvider(cache_dir=tmp_path, source_loader=_krx_unavailable),
    )
    calendar = ProductionTradingCalendar(provider)

    with pytest.raises(HolidayCalendarUnavailableError):
        calendar.prev_trading_day(date(2028, 1, 4))


def test_cache_isolated_by_year(tmp_path):
    krx = KRXHolidayProvider(cache_dir=tmp_path)
    krx._write_cache(2026, {date(2026, 9, 24)}, source="KRX")
    krx._write_cache(2027, {date(2027, 9, 24)}, source="KRX")

    first = krx.load_from_cache(2026)
    second = krx.load_from_cache(2027)

    assert first == {date(2026, 9, 24)}
    assert second == {date(2027, 9, 24)}
