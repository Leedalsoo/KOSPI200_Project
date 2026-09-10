from datetime import datetime
from decimal import Decimal

import pytest

from contracts.kis_index_futures_market_ws_adapter import KisIndexFuturesMarketObservation
from environments.live.market.kis_futures_market_data import (
    KISFuturesMarketDataProvider,
    KISFuturesMarketProjectionError,
)


def observation(price=Decimal("350.10")) -> KisIndexFuturesMarketObservation:
    return KisIndexFuturesMarketObservation(
        shrn_iscd="101S12",
        observed_hour="093000",
        price=price,
        volume=Decimal("1234"),
        ask_price=Decimal("350.20"),
        bid_price=Decimal("350.00"),
        source="KIS:H0IFCNT0",
    )


def test_projection_requires_authoritative_instrument_id_resolver():
    provider = KISFuturesMarketDataProvider(
        observed_at_resolver=lambda _: datetime(2026, 9, 6, 9, 30, 0),
    )
    with pytest.raises(KISFuturesMarketProjectionError, match="INSTRUMENT_ID_RESOLVER_REQUIRED"):
        provider.publish(observation())


def test_projection_requires_authoritative_observed_at_resolver():
    provider = KISFuturesMarketDataProvider(
        instrument_id_resolver=lambda symbol: "FUT-AUTH-1",
    )
    with pytest.raises(KISFuturesMarketProjectionError, match="OBSERVED_AT_RESOLVER_REQUIRED"):
        provider.publish(observation())


def test_projection_preserves_values_and_does_not_synthesize_sequence():
    received = []
    provider = KISFuturesMarketDataProvider(
        instrument_id_resolver=lambda symbol: "FUT-AUTH-1",
        observed_at_resolver=lambda _: datetime(2026, 9, 6, 9, 30, 0),
    )
    provider.subscribe(received.append)

    tick = provider.publish(observation())

    assert tick.instrument_id == "FUT-AUTH-1"
    assert tick.price == Decimal("350.10")
    assert tick.volume == Decimal("1234")
    assert tick.source_sequence is None
    assert received[0].ticks["FUT-AUTH-1"] == tick


def test_quote_only_observation_cannot_be_promoted_to_last_price_tick():
    quote = observation(price=None)
    provider = KISFuturesMarketDataProvider(
        instrument_id_resolver=lambda symbol: "FUT-AUTH-1",
        observed_at_resolver=lambda _: datetime(2026, 9, 6, 9, 30, 0),
    )
    with pytest.raises(KISFuturesMarketProjectionError, match="LAST_PRICE_REQUIRED"):
        provider.publish(quote)
