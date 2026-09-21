from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from application.market_observation_scenario import ScenarioObservationTransformer
from contracts.types import MarketAnalytics, MarketDataProvenance, MarketObservation, MarketOrderBook, MarketQuote, OptionInstrumentIdentity


def test_scenario_transformation_keeps_original_and_records_provenance():
    original = MarketObservation(
        observation_id="obs-original", observed_at=None,
        collected_at=datetime(2026, 9, 21, 12, 26, tzinfo=timezone.utc),
        source="kis_vts_rest", provider="KISOptionRestAdapter",
        schema_version="canonical-market-observation-v1", run_id="run-original",
        contract=OptionInstrumentIdentity(instrument_id="B01610C41", symbol="B01610C41", expiry="202610", option_type="CALL", strike=Decimal("1595")),
        quote=MarketQuote(last=Decimal("0.08"), bid=Decimal("0.08"), ask=Decimal("0.09"), volume=Decimal("1232")),
        order_book=MarketOrderBook(), analytics=MarketAnalytics(), provenance=MarketDataProvenance(),
    )

    result = ScenarioObservationTransformer().transform(
        original,
        scenario_id="wide-spread",
        run_id="run-scenario",
        transform=lambda value: replace(value, quote=replace(value.quote, bid=Decimal("0.05"))),
        metadata={"bid_shift": "-0.03"},
    )

    assert result.observation.observation_id != original.observation_id
    assert result.observation.source == "scenario:wide-spread"
    assert result.observation.run_id == "run-scenario"
    assert result.observation.quote.bid == Decimal("0.05")
    assert result.source_observation_id == "obs-original"
    assert result.scenario_id == "wide-spread"
    assert result.transformation_metadata == (("bid_shift", "-0.03"),)
    assert original.quote.bid == Decimal("0.08")
