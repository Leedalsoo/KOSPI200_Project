from datetime import datetime, timezone
from decimal import Decimal

import pytest

from contracts.track9_iv_timeseries import (
    Track9IVObservation,
    UnavailableTrack9IVTimeSeriesSource,
)


def observation(at: datetime) -> Track9IVObservation:
    return Track9IVObservation(
        symbol="OPT-CALL-350",
        expiry="2026-09",
        option_type="CALL",
        strike=Decimal("350"),
        implied_volatility=Decimal("0.25"),
        observed_at=at,
        source="KIS_H0IOCNT0",
    )


def test_track9_iv_observation_preserves_authoritative_fields():
    at = datetime(2026, 9, 18, 1, 0, tzinfo=timezone.utc)
    item = observation(at)
    assert item.symbol == "OPT-CALL-350"
    assert item.implied_volatility == Decimal("0.25")
    assert item.observed_at == at
    assert item.source == "KIS_H0IOCNT0"


def test_unavailable_source_fails_closed_on_append_and_returns_no_history():
    source = UnavailableTrack9IVTimeSeriesSource()
    at = datetime(2026, 9, 18, 1, 0, tzinfo=timezone.utc)
    with pytest.raises(RuntimeError, match="TRACK9_IV_TIMESERIES_UNAVAILABLE"):
        source.append(observation(at))
    assert source.query(
        symbol="OPT-CALL-350", expiry="2026-09", option_type="CALL",
        strike=Decimal("350"), start=at, end=at.replace(hour=2)
    ) == ()
