from datetime import datetime, timezone
from decimal import Decimal

from application.historical_market_data_provider import HistoricalMarketDataProvider
from application.market_data_hub import MarketDataHub
from contracts.types import (
    MarketAnalytics,
    MarketDataProvenance,
    MarketObservation,
    MarketOrderBook,
    MarketQuote,
    OptionInstrumentIdentity,
)
from environments.virtual.market.historical_market_store import HistoricalMarketStore
from environments.virtual.market.replay_engine import HistoricalReplayEngine


def make_observation() -> MarketObservation:
    return MarketObservation(
        observation_id="obs-hub-1", observed_at=datetime(2026, 9, 21, 12, 26, tzinfo=timezone.utc),
        collected_at=datetime(2026, 9, 21, 12, 26, 1, tzinfo=timezone.utc),
        source="kis_vts_rest", provider="KISOptionRestAdapter",
        schema_version="canonical-market-observation-v1", run_id="run-hub",
        contract=OptionInstrumentIdentity(
            instrument_id="B01610C41", symbol="B01610C41", expiry="202610",
            option_type="CALL", strike=Decimal("1595"),
        ),
        quote=MarketQuote(last=Decimal("0.08"), bid=Decimal("0.08"), ask=Decimal("0.09"), volume=Decimal("1232")),
        order_book=MarketOrderBook(), analytics=MarketAnalytics(), provenance=MarketDataProvenance(),
        underlying_price=Decimal("1130.63"), underlying_symbol="KOSPI200",
        underlying_observed_hour="122603", underlying_source="kis_vts_rest:price.output3",
    )


def test_observation_round_trips_store_replay_and_hub_without_kis_fields(tmp_path):
    store = HistoricalMarketStore(tmp_path / "market.jsonl")
    observation = make_observation()
    store.append_observation(observation)

    replay = HistoricalReplayEngine([HistoricalReplayEngine.project_observation(item) for item in store.load_observations()])
    provider = HistoricalMarketDataProvider(replay)
    hub = MarketDataHub({"historical": provider}, active="historical")

    tick = provider.replay_next()
    assert tick.instrument_id == "B01610C41"
    assert tick.underlying_price == Decimal("1130.63")
    assert tick.underlying_symbol == "KOSPI200"
    assert store.load_observations()[0].underlying_price == Decimal("1130.63")
    state = hub.snapshot()
    assert state.ticks["B01610C41"].price == Decimal("1130.63")
    assert not hasattr(state.ticks["B01610C41"], "optn_prpr")
