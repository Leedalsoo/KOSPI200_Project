from decimal import Decimal

from application.bootstrap import create_virtual_runtime_bootstrap
from application.composition.virtual_runtime_data_provider import VirtualRuntimeDataProvider


def test_virtual_runtime_data_provider_uses_vms_observations_and_explicit_unavailable_sources():
    bootstrap = create_virtual_runtime_bootstrap()
    market = bootstrap.bundle.market
    provider = VirtualRuntimeDataProvider(market)
    ticks = list(market.generate_tick_stream(total_days=1, ticks_per_day=4))
    data = provider.snapshot(ticks[-1])

    assert data.price == Decimal(str(ticks[-1].last_price))
    assert data.as_of.isoformat() == ticks[-1].timestamp
    assert data.prices
    assert data.high_price >= data.low_price
    assert data.status["tick"].available is True
    assert data.status["ohlc_history"].source == "VMS.recent_ticks"
    assert data.status["macro"].available is True
    assert data.status["macro"].source == "VMS.scenario.active_config"
    assert data.status["event"].available is True
    assert data.status["event"].source == "VMS.scenario.shock_schedule"




def test_virtual_runtime_can_replay_authoritative_rest_observation_store(tmp_path):
    from datetime import datetime, timezone
    from contracts.types import (
        MarketAnalytics, MarketDataProvenance, MarketObservation,
        MarketOrderBook, MarketQuote, OptionInstrumentIdentity,
    )
    from environments.virtual.market.historical_market_store import HistoricalMarketStore
    from environments.virtual.market.simulator_runtime import VirtualMarketSimulatorRuntime

    store = HistoricalMarketStore(tmp_path / "market.jsonl")
    identity = OptionInstrumentIdentity(
        "C01610A29", "C01610A29", "202610", "PUT",
        Decimal("1075"), Decimal("250000"),
    )
    for i in range(4):
        observed = datetime(2026, 9, 21, 5, 45, i, tzinfo=timezone.utc)
        store.append_observation(MarketObservation(
            observation_id=f"obs-{i}", observed_at=observed, collected_at=observed,
            source="kis_vts_rest", provider="KISOptionRestAdapter",
            schema_version="canonical-market-observation-v1", run_id="run-1",
            contract=identity,
            quote=MarketQuote(last=Decimal("32.8"), bid=Decimal("22"), ask=Decimal("23.45"), volume=Decimal("1")),
            order_book=MarketOrderBook(), analytics=MarketAnalytics(),
            provenance=MarketDataProvenance(),
        ))
    runtime = VirtualMarketSimulatorRuntime()
    seen = []
    runtime.subscribe(seen.append)
    runtime.load_historical_observation_store(store, source="kis_vts_rest")
    [runtime.replay_next() for _ in range(4)]
    assert len(seen) == 4
    assert runtime.replay.exhausted
    assert seen[-1].symbol == "C01610A29"
