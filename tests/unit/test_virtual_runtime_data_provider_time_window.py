from datetime import datetime, timedelta, timezone
from decimal import Decimal

from application.composition.virtual_runtime_data_provider import VirtualRuntimeDataProvider


def _reference(history, as_of, minutes):
    cutoff = as_of.timestamp() - minutes * 60
    points = [(timestamp, Decimal(str(price))) for timestamp, price in history if timestamp <= as_of]
    if not points or points[0][0].timestamp() > cutoff:
        return None
    values = [price for timestamp, price in points if timestamp.timestamp() >= cutoff]
    if not values:
        return None
    return sum(values, Decimal("0")) / Decimal(len(values))


def test_time_window_ma_matches_reference_for_sorted_history():
    start = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)
    history = tuple(
        (start + timedelta(seconds=15 * i), Decimal(str(100 + i)))
        for i in range(80)
    )
    as_of = start + timedelta(minutes=17, seconds=30)

    for minutes in (1, 3, 5, 10):
        assert VirtualRuntimeDataProvider._time_window_ma(history, as_of, minutes) == _reference(
            history, as_of, minutes
        )


def test_time_window_ma_returns_none_when_window_has_no_history():
    start = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)
    history = ((start, Decimal("100")),)
    as_of = start + timedelta(minutes=2)

    assert VirtualRuntimeDataProvider._time_window_ma(history, as_of, 1) is None
