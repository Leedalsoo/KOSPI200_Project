from decimal import Decimal
from types import SimpleNamespace

import pytest

from application.composition.virtual_runtime_data_provider import VirtualRuntimeDataProvider
from contracts.kis_index_option_market_ws_adapter import KISIndexOptionMarketWebSocketAdapter
from infrastructure.kis.option_orderbook_source import KISOptionOrderBookSource
from environments.virtual.market.simulator_runtime import VirtualMarketSimulatorRuntime


def _quote_frame(symbol: str = "201S11305") -> str:
    asks = ["3.35", "3.40", "3.45", "3.50", "3.55"]
    bids = ["3.25", "3.20", "3.15", "3.10", "3.05"]
    quantities = ["10", "20", "30", "40", "50"]
    values = [symbol, "101531", *asks, *bids, *( ["1"] * 10), *(quantities * 2), "50", "50", "150", "150", "0", "0"]
    return f"0|H0IOASP0|{len(values)}|{'^'.join(values)}"


def _tick(symbol: str = "201S11305"):
    return SimpleNamespace(
        timestamp="2026-09-16T10:15:31",
        last_price=3.30,
        bid_price=3.25,
        ask_price=3.35,
        strike_price=510.0,
        expiry="202610",
        symbol=symbol,
        seq_id=1,
    )


def test_h0ioasp0_orderbook_preserves_five_levels_and_quantities() -> None:
    source = KISOptionOrderBookSource()
    observation = KISIndexOptionMarketWebSocketAdapter().adapt(_quote_frame())
    source.update(observation)

    book = source.get_order_book("201S11305")
    assert book is not None
    assert book.source == "KIS:H0IOASP0"
    assert book.ask_quantities == tuple(Decimal(x) for x in ["10", "20", "30", "40", "50"])
    assert book.bid_quantities == tuple(Decimal(x) for x in ["10", "20", "30", "40", "50"])
    assert book.ask_levels[0].price == Decimal("3.35")
    assert book.bid_levels[0].price == Decimal("3.25")


def test_runtime_input_receives_authoritative_orderbook_quantities() -> None:
    source = KISOptionOrderBookSource()
    source.update(KISIndexOptionMarketWebSocketAdapter().adapt(_quote_frame()))
    market = VirtualMarketSimulatorRuntime()
    provider = VirtualRuntimeDataProvider(market, option_orderbook_source=source)

    data = provider.snapshot(_tick())

    assert data.option_bid_qtys == tuple(Decimal("10") for _ in range(1)) + tuple(Decimal(x) for x in ["20", "30", "40", "50"])
    assert data.option_ask_qtys == tuple(Decimal(x) for x in ["10", "20", "30", "40", "50"])
    assert data.status["option_orderbook"].available is True
    assert data.status["option_orderbook"].source == "KIS:H0IOASP0"


def test_runtime_input_fails_closed_when_orderbook_source_is_missing() -> None:
    market = VirtualMarketSimulatorRuntime()
    provider = VirtualRuntimeDataProvider(market)

    data = provider.snapshot(_tick())

    assert data.option_bid_qtys is None
    assert data.option_ask_qtys is None
    assert data.status["option_orderbook"].available is False
    assert data.status["option_orderbook"].reason == "OPTION_ORDERBOOK_SOURCE_UNAVAILABLE"


def test_orderbook_source_rejects_identity_mismatch() -> None:
    source = KISOptionOrderBookSource()
    observation = KISIndexOptionMarketWebSocketAdapter().adapt(_quote_frame("201S11305"))
    bad = observation.__class__(
        shrn_iscd="201S11306",
        observed_hour=observation.observed_hour,
        last_price=observation.last_price,
        ask_price=observation.ask_price,
        bid_price=observation.bid_price,
        volume=observation.volume,
        source=observation.source,
        order_book=observation.order_book,
    )
    with pytest.raises(ValueError, match="IDENTITY_OR_DEPTH"):
        source.update(bad)
