from datetime import date
from types import SimpleNamespace

from environments.high_speed.synthetic_runtime_sources import SyntheticTradingCalendar


def test_synthetic_calendar_preserves_authoritative_exact_expiry_date():
    calendar = SyntheticTradingCalendar()

    assert calendar.resolve_option_expiry(SimpleNamespace(expiry="2026-10-08")) == date(2026, 10, 8)
    assert calendar.resolve_option_expiry(SimpleNamespace(expiry="20261008")) == date(2026, 10, 8)


def test_legacy_month_only_expiry_uses_second_thursday_not_third_thursday():
    calendar = SyntheticTradingCalendar()

    assert calendar.resolve_option_expiry(SimpleNamespace(expiry="202610")) == date(2026, 10, 8)
