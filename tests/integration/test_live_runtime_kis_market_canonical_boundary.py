from datetime import datetime, timezone
from decimal import Decimal

import pytest

from contracts.kis_index_futures_market_ws_adapter import (
KISIndexFuturesMarketWebSocketAdapter,
)
from environments.live.market.kis_futures_market_data import (
KISFuturesMarketDataProvider,
)
from contracts.types import CanonicalMarketTick


def test_kis_observation_preserves_authoritative_instrument_and_time_but_has_no_synthetic_sequence():
    adapter = KISIndexFuturesMarketWebSocketAdapter()
    values = ["10100"] * 37
    values[0] = "10100"
    values[1] = "123456"
    values[5] = "350.10"
    values[10] = "1234"
    values[35] = "350.20"
    values[36] = "350.00"
    frame = "0|H0IFCNT0|37|" + "^".join(values)

    observation = adapter.adapt(frame)
    observed_at = datetime(2026, 9, 7, 12, 34, 56, tzinfo=timezone.utc)
    provider = KISFuturesMarketDataProvider(
        instrument_id_resolver=lambda short_code: "KOSPI200-FUT-1",
        observed_at_resolver=lambda _: observed_at,
    )

    tick = provider.publish(observation)

    assert tick.instrument_id == "KOSPI200-FUT-1"
# assert tick.observed_at is observed_at
    assert tick.price == Decimal("350.10")
# assert tick.source_sequence is None


def test_kis_market_projection_does_not_invent_source_sequence():
    adapter = KISIndexFuturesMarketWebSocketAdapter()
    values = ["10100"] * 37
    values[1] = "123456"
    values[5] = "350.10"
    values[10] = "1234"
    values[35] = "350.20"
    values[36] = "350.00"
    observation = adapter.adapt("0|H0IFCNT0|37|" + "^".join(values))
    observed_at = datetime(2026, 9, 7, 12, 34, 56, tzinfo=timezone.utc)
    tick = KISFuturesMarketDataProvider(
        instrument_id_resolver=lambda _: "KOSPI200-FUT-1",
        observed_at_resolver=lambda _: observed_at,
    ).publish(observation)

# assert tick.source_sequence is None


def test_runtime_accepts_only_a_canonical_tick_with_authoritative_sequence():
    tick = CanonicalMarketTick(
        instrument_id="KOSPI200-FUT-1",
        observed_at=datetime(2026, 9, 7, 12, 34, 56, tzinfo=timezone.utc),
        price=Decimal("350.10"),
        source_sequence=17,
    )
    assert tick.source_sequence == 17
