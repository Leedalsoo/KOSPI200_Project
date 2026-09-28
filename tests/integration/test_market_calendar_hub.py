from datetime import date, timedelta

from application.composition.market_calendar_hub import MarketCalendarHub
from infrastructure.kis.holiday_fallback_provider import HolidayResolutionStatus


class FakeCalendar:
    def __init__(self):
        self.closed = {date(2026, 9, 24), date(2026, 9, 25)}

    def is_trading_day(self, value):
        return value.weekday() < 5 and value not in self.closed

    def prev_trading_day(self, value):
        current = value - timedelta(days=1)
        while not self.is_trading_day(current):
            current -= timedelta(days=1)
        return current

    def holiday_resolution(self, year):
        return type(
            "Resolution",
            (),
            {"status": HolidayResolutionStatus.KRX, "source": "KRX:test"},
        )()


def test_market_calendar_hub_is_common_read_model():
    hub = MarketCalendarHub(FakeCalendar())

    snapshot = hub.snapshot(date(2026, 9, 28), expiry=date(2026, 10, 8))

    assert snapshot.available
    assert snapshot.is_trading_day is True
    assert snapshot.is_holiday is False
    assert snapshot.previous_trading_day == date(2026, 9, 23)
    assert snapshot.is_new_week_start is True
    assert snapshot.is_expiry_day is False
    assert snapshot.source == "KRX:test"


def test_market_calendar_hub_fail_closed_when_calendar_is_unknown():
    class UnknownCalendar:
        def is_trading_day(self, value):
            raise RuntimeError("calendar unavailable")

    snapshot = MarketCalendarHub(UnknownCalendar()).snapshot(date(2028, 1, 4))

    assert snapshot.status.value == "UNKNOWN"
    assert snapshot.is_trading_day is None
    assert snapshot.previous_trading_day is None
