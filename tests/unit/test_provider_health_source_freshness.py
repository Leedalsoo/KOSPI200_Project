from datetime import datetime, timedelta, timezone
from decimal import Decimal

from contracts.kis_index_futures_market_ws_adapter import KisIndexFuturesMarketObservation
from environments.live.market.kis_futures_market_data import KISFuturesMarketDataProvider


def test_kis_provider_health_preserves_source_and_observed_at():
    observed_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    provider = KISFuturesMarketDataProvider(
        instrument_id_resolver=lambda symbol: f"KOSPI200:{symbol}",
        observed_at_resolver=lambda _: observed_at,
    )
    provider.publish(KisIndexFuturesMarketObservation(
        shrn_iscd="101V6000", observed_hour="090000", price=Decimal("510"),
        volume=Decimal("10"), ask_price=Decimal("511"), bid_price=Decimal("509"),
        source="KIS:H0IFCNT0",
    ))
    health = provider.health()
    assert health.available is True
    assert health.source == "KIS:H0IFCNT0"
    assert health.observed_at == observed_at
    assert health.freshness_seconds is not None
    assert health.freshness_seconds >= 0


def test_kis_provider_health_is_explicitly_unavailable_before_first_observation():
    provider = KISFuturesMarketDataProvider()
    health = provider.health()
    assert health.available is False
    assert health.source is None
    assert health.observed_at is None
    assert health.freshness_seconds is None
