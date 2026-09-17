from datetime import datetime
from decimal import Decimal

import pytest

from application.composition.track7_order_timeout_source import Track7OrderTimeoutRuntimeSource
from contracts.track7_order_timeout import Track7OrderTimeoutPolicy
from environments.virtual.clock import VirtualClock


def test_timeout_uses_runtime_clock_and_explicit_policy():
    clock = VirtualClock(datetime(2026, 9, 17, 9, 0, 0))
    source = Track7OrderTimeoutRuntimeSource(
        clock, Track7OrderTimeoutPolicy(Decimal("5"), "TRACK7-LIMIT-5S")
    )
    source.observe_submission("O1", "track7_volatility_skew_weekly_insurance", clock.now())
    clock.sleep_policy(4)
    assert source.is_timed_out("O1", clock.now(), "NEW") is False
    clock.sleep_policy(1)
    assert source.is_timed_out("O1", clock.now(), "NEW") is True


def test_terminal_order_never_times_out():
    clock = VirtualClock(datetime(2026, 9, 17, 9, 0, 0))
    source = Track7OrderTimeoutRuntimeSource(
        clock, Track7OrderTimeoutPolicy(Decimal("5"), "TRACK7-LIMIT-5S")
    )
    source.observe_submission("O2", "track7_volatility_skew_weekly_insurance", clock.now())
    clock.sleep_policy(10)
    assert source.is_timed_out("O2", clock.now(), "FILLED") is False


def test_missing_lifecycle_submission_fails_closed():
    clock = VirtualClock(datetime(2026, 9, 17, 9, 0, 0))
    source = Track7OrderTimeoutRuntimeSource(
        clock, Track7OrderTimeoutPolicy(Decimal("5"), "TRACK7-LIMIT-5S")
    )
    with pytest.raises(KeyError, match="TRACK7_ORDER_LIFECYCLE_SUBMISSION_UNAVAILABLE"):
        source.is_timed_out("MISSING", clock.now(), "NEW")
