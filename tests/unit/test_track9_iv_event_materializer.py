from datetime import datetime
from decimal import Decimal

import pytest

from contracts.track9_iv_event_materializer import (
    Track9ATMIVSnapshot,
    Track9IVEventMaterializer,
)


class FakeATMSource:
    def __init__(self, snapshots):
        self.snapshots = iter(snapshots)

    def snapshot(self, **kwargs):
        return next(self.snapshots)


def snapshot(at, call, put, strike=510):
    return Track9ATMIVSnapshot(
        symbol="201C51000",
        expiry="2026-10-15",
        strike=Decimal(str(strike)),
        call_iv=Decimal(str(call)),
        put_iv=Decimal(str(put)),
        observed_at=at,
        source="KIS:H0IOCNT0",
    )


def test_baseline_captures_once_at_session_start_and_current_delta_is_pct_point():
    start = datetime(2026, 9, 18, 9, 0)
    now = datetime(2026, 9, 18, 10, 0)
    source = FakeATMSource([
        snapshot(start, "0.240", "0.260"),
        snapshot(now, "0.280", "0.300"),
    ])
    values = Track9IVEventMaterializer()

    values.materialize(session_date="2026-09-18", symbol="201C51000", expiry="2026-10-15", current_price=Decimal("510"), observed_at=start, source=source)
    result = values.materialize(session_date="2026-09-18", symbol="201C51000", expiry="2026-10-15", current_price=Decimal("510"), observed_at=now, source=source)

    assert result.baseline_iv == Decimal("0.250")
    assert result.current_iv == Decimal("0.290")
    assert result.iv_spike == Decimal("4.00")
    assert result.iv_crush == Decimal("0")
    assert result.status == "READY"


def test_negative_delta_materializes_crush_only():
    start = datetime(2026, 9, 18, 9, 0)
    now = datetime(2026, 9, 18, 10, 0)
    source = FakeATMSource([
        snapshot(start, "0.300", "0.300"),
        snapshot(now, "0.270", "0.270"),
    ])
    materializer = Track9IVEventMaterializer()
    materializer.materialize(session_date="2026-09-18", symbol="201C51000", expiry="2026-10-15", current_price=Decimal("510"), observed_at=start, source=source)
    result = materializer.materialize(session_date="2026-09-18", symbol="201C51000", expiry="2026-10-15", current_price=Decimal("510"), observed_at=now, source=source)

    assert result.iv_spike == Decimal("0")
    assert result.iv_crush == Decimal("-3.00")


def test_missing_0900_observation_does_not_use_later_observation_as_baseline():
    now = datetime(2026, 9, 18, 9, 1)
    source = FakeATMSource([snapshot(now, "0.240", "0.260")])
    result = Track9IVEventMaterializer().materialize(
        session_date="2026-09-18", symbol="201C51000", expiry="2026-10-15",
        current_price=Decimal("510"), observed_at=now, source=source,
    )
    assert result.status == "BASELINE_UNAVAILABLE"
    assert result.iv_spike is None
    assert result.iv_crush is None


def test_baseline_resets_each_trading_day():
    day1 = datetime(2026, 9, 18, 9, 0)
    day2 = datetime(2026, 9, 21, 9, 0)
    source = FakeATMSource([
        snapshot(day1, "0.200", "0.200"),
        snapshot(day2, "0.300", "0.300"),
    ])
    materializer = Track9IVEventMaterializer()
    first = materializer.materialize(session_date="2026-09-18", symbol="201C51000", expiry="2026-10-15", current_price=Decimal("510"), observed_at=day1, source=source)
    second = materializer.materialize(session_date="2026-09-21", symbol="201C51000", expiry="2026-10-15", current_price=Decimal("510"), observed_at=day2, source=source)
    assert first.baseline_iv == Decimal("0.200")
    assert second.baseline_iv == Decimal("0.300")
    assert second.iv_spike == Decimal("0")
    assert second.iv_crush == Decimal("0")


def test_invalid_iv_fails_closed():
    start = datetime(2026, 9, 18, 9, 0)
    source = FakeATMSource([snapshot(start, "0", "0")])
    with pytest.raises(ValueError, match="TRACK9_IV_INVALID"):
        Track9IVEventMaterializer().materialize(
            session_date="2026-09-18", symbol="201C51000", expiry="2026-10-15",
            current_price=Decimal("510"), observed_at=start, source=source,
        )
