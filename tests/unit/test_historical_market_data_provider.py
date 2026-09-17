from datetime import datetime, timezone
from decimal import Decimal

from application.historical_market_data_provider import HistoricalMarketDataProvider
from application.market_data_hub import MarketDataHub
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick
from environments.virtual.market.replay_engine import HistoricalReplayEngine


def _tick(source="KRX:HISTORICAL"):
    return ReferenceCanonicalMarketTick(
        timestamp="2026-09-17T10:00:00+00:00",
        underlying_price=510.25,
        underlying_symbol="KOSPI200",
        last_price=510.25,
        volume=120,
        seq_id=7,
        symbol="201S11305",
        option_source=source,
        expiry="202610",
        strike_price=510.0,
        option_type="CALL",
    )


def test_replay_projects_to_standard_provider_contract():
    provider = HistoricalMarketDataProvider(HistoricalReplayEngine([_tick()]))
    assert provider.replay_next().price == Decimal("510.25")
    state = provider.snapshot()
    assert state.ticks["201S11305"].seq_id == 7
    health = provider.health()
    assert health.source == "KRX:HISTORICAL"
    assert health.observed_at == datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc)
    assert health.freshness_seconds is not None


def test_historical_provider_can_be_selected_by_market_data_hub():
    provider = HistoricalMarketDataProvider(HistoricalReplayEngine([_tick()]))
    hub = MarketDataHub({"historical": provider}, active="historical")
    assert hub.active_provider == "historical"
    provider.replay_next()
    assert hub.snapshot().as_of == datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc)
    assert hub.health().source == "KRX:HISTORICAL"


def test_historical_provider_fails_closed_without_market_data():
    provider = HistoricalMarketDataProvider(HistoricalReplayEngine())
    health = provider.health()
    assert health.available is False
    assert health.source is None
    assert health.observed_at is None
    assert health.freshness_seconds is None
