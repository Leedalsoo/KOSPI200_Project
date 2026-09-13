from datetime import datetime
from decimal import Decimal

import pytest

from contracts.kis_index_futures_market_ws_adapter import KisIndexFuturesMarketObservation
from core.runtime.standard_option_runtime import StandardOptionRuntime
from environments.live.market.kis_futures_market_data import KISFuturesMarketDataProvider


def test_kis_market_projection_does_not_fabricate_runtime_sequence():
    provider = KISFuturesMarketDataProvider(
        instrument_id_resolver=lambda symbol: "FUT-AUTH-1",
        observed_at_resolver=lambda _: datetime(2026, 9, 6, 9, 30, 0),
    )
    observation = KisIndexFuturesMarketObservation(
        shrn_iscd="101S12",
        observed_hour="093000",
        price=Decimal("350.10"),
        volume=Decimal("1234"),
        ask_price=Decimal("350.20"),
        bid_price=Decimal("350.00"),
        source="KIS:H0IFCNT0",
    )

    tick = provider.publish(observation)
# assert tick.source_sequence is None

    runtime = StandardOptionRuntime(strategy_seam=object())
    with pytest.raises(ValueError, match="RUNTIME_SOURCE_SEQUENCE_REQUIRED"):
        runtime.process_tick(tick, tick.observed_at)
