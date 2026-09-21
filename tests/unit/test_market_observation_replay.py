from datetime import datetime, timezone
from decimal import Decimal

import pytest

from contracts.types import (
    MarketAnalytics,
    MarketDataProvenance,
    MarketObservation,
    MarketOrderBook,
    MarketQuote,
    OptionInstrumentIdentity,
)
from environments.virtual.market.replay_engine import HistoricalReplayEngine


def observation(*, observed_at=None):
    return MarketObservation(
        observation_id="obs-1", observed_at=observed_at,
        collected_at=datetime(2026, 9, 21, 12, 26, 3, 450000, tzinfo=timezone.utc),
        source="kis_vts_rest", provider="KISOptionRestAdapter",
        schema_version="canonical-market-observation-v1", run_id="run-1",
        contract=OptionInstrumentIdentity(
            instrument_id="B01610C41", symbol="B01610C41", expiry="202610",
            option_type="CALL", strike=Decimal("1595.0"), contract_multiplier=Decimal("250000"),
        ),
        quote=MarketQuote(last=Decimal("0.08"), bid=Decimal("0.08"), ask=Decimal("0.09"), volume=Decimal("1232")),
        order_book=MarketOrderBook(), analytics=MarketAnalytics(), provenance=MarketDataProvenance(),
    )


def test_rest_observation_has_explicit_legacy_projection():
    tick = HistoricalReplayEngine.project_observation(observation())

    assert tick.symbol == "B01610C41"
    assert tick.strike_price == 1595.0
    assert tick.bid_price == 0.08
    assert tick.ask_price == 0.09
    assert tick.last_price == 0.08
    assert tick.volume == 1232
    assert tick.timestamp == "2026-09-21T12:26:03.450000+00:00"


def test_authoritative_observed_at_is_preferred_for_replay_time_axis():
    observed_at = datetime(2026, 9, 21, 12, 25, 59, tzinfo=timezone.utc)
    tick = HistoricalReplayEngine.project_observation(observation(observed_at=observed_at))

    assert tick.timestamp == "2026-09-21T12:25:59+00:00"


def test_observation_store_loads_into_legacy_replay_explicitly(tmp_path):
    from environments.virtual.market.historical_market_store import HistoricalMarketStore

    store = HistoricalMarketStore(tmp_path / "market.jsonl")
    store.append_observation(observation())

    replay = HistoricalReplayEngine.from_observation_store(store, source="kis_vts_rest")
    tick = replay.next_tick()

    assert tick is not None
    assert tick.symbol == "B01610C41"
    assert tick.last_price == 0.08


def test_projection_fails_closed_when_legacy_required_quote_is_missing():
    source = observation()
    incomplete = MarketObservation(
        observation_id=source.observation_id, observed_at=source.observed_at,
        collected_at=source.collected_at, source=source.source, provider=source.provider,
        schema_version=source.schema_version, run_id=source.run_id, contract=source.contract,
        quote=MarketQuote(last=None, bid=source.quote.bid, ask=source.quote.ask, volume=source.quote.volume),
        order_book=source.order_book, analytics=source.analytics, provenance=source.provenance,
    )

    with pytest.raises(ValueError, match="LEGACY_TICK_REQUIRED_MARKET_VALUE_MISSING"):
        HistoricalReplayEngine.project_observation(incomplete)
