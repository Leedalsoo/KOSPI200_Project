from datetime import date
import unittest

from infrastructure.kis.trading_calendar import ProductionTradingCalendar


class _HolidayProvider:
    def __init__(self, holidays):
        self.holidays = set(holidays)

    def is_holiday(self, value):
        return value in self.holidays


class ProductionTradingCalendarTests(unittest.TestCase):
    def setUp(self):
        self.calendar = ProductionTradingCalendar(
            _HolidayProvider({date(2026, 3, 2)})
        )

    def test_weekday_and_holiday_boundaries(self):
        self.assertTrue(self.calendar.is_trading_day(date(2026, 2, 27)))
        self.assertFalse(self.calendar.is_trading_day(date(2026, 2, 28)))
        self.assertFalse(self.calendar.is_trading_day(date(2026, 3, 2)))

    def test_prev_trading_day_skips_weekend_and_holiday(self):
        self.assertEqual(
            self.calendar.prev_trading_day(date(2026, 3, 3)),
            date(2026, 2, 27),
        )

    def test_trading_days_between(self):
        self.assertEqual(
            self.calendar.trading_days_between(date(2026, 2, 27), date(2026, 3, 3)),
# 1,
        )


if __name__ == "__main__":
    pass
# unittest.main()
