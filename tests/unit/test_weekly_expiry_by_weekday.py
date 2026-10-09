from datetime import date, timedelta

import pytest

from core.option.option_master import (
    _calculate_expiry,
    calculate_krx_weekly_option_expiry,
)


class KRXCalendar:
    holidays = {date(2026, 9, 24)}

    def is_trading_day(self, value: date) -> bool:
        return value.weekday() < 5 and value not in self.holidays

    def prev_trading_day(self, value: date) -> date:
        candidate = value - timedelta(days=1)
        while not self.is_trading_day(candidate):
            candidate -= timedelta(days=1)
        return candidate


def test_monday_weekly_expiry_uses_monday_family():
    calendar = KRXCalendar()
    assert calculate_krx_weekly_option_expiry(2026, 9, 3, calendar, weekday=0) == "2026-09-21"
    assert _calculate_expiry("BAK47044", "코스피위클리M P 2609W3 1210", calendar) == "2026-09-21"


def test_thursday_weekly_expiry_moves_back_for_krx_holiday():
    calendar = KRXCalendar()
    assert calculate_krx_weekly_option_expiry(2026, 9, 4, calendar, weekday=3) == "2026-09-23"
    assert _calculate_expiry("CAJ36044", "코스피위클리 P 2609W4 1180", calendar) == "2026-09-23"


def test_second_thursday_weekly_series_is_rejected():
    with pytest.raises(ValueError, match="SECOND_THURSDAY"):
        calculate_krx_weekly_option_expiry(2026, 9, 2, KRXCalendar(), weekday=3)
