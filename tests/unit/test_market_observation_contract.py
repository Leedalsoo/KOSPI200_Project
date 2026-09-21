from dataclasses import FrozenInstanceError
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
    OrderBookLevel,
    RawMarketDataReference,
)


def make_observation() -> MarketObservation:
    return MarketObservation(
        observation_id="obs-1",
        observed_at=datetime(2026, 9, 21, 12, 26, 3, tzinfo=timezone.utc),
        collected_at=datetime(2026, 9, 21, 12, 26, 3, 450000, tzinfo=timezone.utc),
        source="kis_vts_rest",
        provider="KISOptionRestAdapter",
        schema_version="canonical-market-observation-v1",
        run_id="run-1",
        contract=OptionInstrumentIdentity(
            instrument_id="B01610C41",
            symbol="B01610C41",
            expiry="202610",
            option_type="CALL",
            strike=Decimal("1595.0"),
            contract_multiplier=Decimal("250000"),
            identity_source="kis_vts_rest",
        ),
        quote=MarketQuote(
            last=Decimal("0.08"),
            bid=Decimal("0.08"),
            ask=Decimal("0.09"),
            volume=Decimal("1232"),
        ),
        order_book=MarketOrderBook(
            bids=(OrderBookLevel(level=1, price=Decimal("0.08"), quantity=Decimal("2740")),),
            asks=(OrderBookLevel(level=1, price=Decimal("0.09"), quantity=Decimal("744")),),
            total_bid_quantity=Decimal("2740"),
            total_ask_quantity=Decimal("744"),
        ),
        analytics=MarketAnalytics(
            implied_volatility=Decimal("57.1599"),
            delta=Decimal("0.0185"),
        ),
        provenance=MarketDataProvenance(
            endpoints=("/uapi/domestic-futureoption/v1/quotations/inquire-price",),
            tr_ids=("FHMIF10000000",),
        ),
        raw_reference=RawMarketDataReference(
            raw_id="raw-1",
            content_hash="abc123",
        ),
    )


def test_market_observation_retains_complete_immutable_contract():
    observation = make_observation()

    assert observation.contract.symbol == "B01610C41"
    assert observation.quote.last == Decimal("0.08")
    assert observation.order_book.asks[0].quantity == Decimal("744")
    assert observation.analytics.delta == Decimal("0.0185")
    assert observation.observed_at < observation.collected_at
    assert observation.raw_reference.raw_id == "raw-1"

    with pytest.raises(FrozenInstanceError):
        observation.observation_id = "changed"


def test_market_observation_preserves_absent_fields_as_none():
    quote = MarketQuote(last=Decimal("0.08"), bid=None, ask=None, volume=None)
    analytics = MarketAnalytics(implied_volatility=None, delta=None)

    assert quote.bid is None
    assert quote.ask is None
    assert quote.volume is None
    assert analytics.implied_volatility is None
    assert analytics.delta is None


def test_market_observation_rejects_missing_required_identity():
    with pytest.raises(ValueError, match="MARKET_OBSERVATION_CONTRACT_ID_REQUIRED"):
        MarketObservation(
            observation_id="",
            observed_at=None,
            collected_at=datetime.now(timezone.utc),
            source="kis_vts_rest",
            provider="KISOptionRestAdapter",
            schema_version="canonical-market-observation-v1",
            run_id="run-1",
            contract=OptionInstrumentIdentity(instrument_id="", symbol=""),
            quote=MarketQuote(),
            order_book=MarketOrderBook(),
            analytics=MarketAnalytics(),
            provenance=MarketDataProvenance(),
            raw_reference=None,
        )
