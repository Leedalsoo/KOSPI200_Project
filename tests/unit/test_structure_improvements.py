from datetime import date

import pytest

from application.composition.execution_multi_leg_resolver_registry import ExecutionMultiLegResolverRegistry
from application.composition.market_calendar_hub import MarketCalendarHub


class Calendar:
    def __init__(self, days):
        self.days = set(days)

    def is_trading_day(self, value):
        return value in self.days

    def prev_trading_day(self, value):
        current = value
        while True:
            current = current.fromordinal(current.toordinal() - 1)
            if self.is_trading_day(current):
                return current

    def holiday_resolution(self, year):
        return type("Resolution", (), {"status": "AVAILABLE", "source": "TEST_CALENDAR"})()


def test_market_calendar_hub_owns_week_boundaries():
    days = {date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23), date(2026, 9, 28), date(2026, 9, 29)}
    snapshot = MarketCalendarHub(Calendar(days)).snapshot(date(2026, 9, 28))
    assert snapshot.available
    assert snapshot.is_new_week_start is True
    assert snapshot.previous_trading_day == date(2026, 9, 23)


def test_market_calendar_hub_fail_closes_when_calendar_is_missing():
    hub = MarketCalendarHub(None)
    snapshot = hub.snapshot(date(2026, 9, 28))
    assert not snapshot.available
    with pytest.raises(ValueError, match="MARKET_CALENDAR_SNAPSHOT_UNAVAILABLE"):
        hub.flags(date(2026, 9, 28))


def test_execution_resolver_registry_dispatches_by_strategy_id():
    registry = ExecutionMultiLegResolverRegistry()
    registry.register("track6", lambda evaluation, canonical: (evaluation, canonical))
    marker = object()
    assert registry.resolve("track6", marker, "signal") == (marker, "signal")
    assert registry.resolve("unknown", marker, "signal") is None
    assert registry.registered_strategy_ids() == ("track6",)


def test_execution_resolver_registry_rejects_duplicates():
    registry = ExecutionMultiLegResolverRegistry()
    registry.register("track6", lambda *_: None)
    with pytest.raises(ValueError, match="ALREADY_REGISTERED"):
        registry.register("track6", lambda *_: None)
