from datetime import datetime, timezone
from decimal import Decimal

from contracts.types import MarketAnalytics, MarketDataProvenance, MarketObservation, MarketOrderBook, MarketQuote, OptionInstrumentIdentity, OrderBookLevel
from infrastructure.kis.historical_observation_sources import HistoricalObservationOptionSource


def _observation(symbol, option_type, strike, observed_at, iv):
    return MarketObservation(
        observation_id=f"obs-{symbol}-{observed_at.isoformat()}",
        observed_at=observed_at,
        collected_at=observed_at,
        source="kis_vts_rest",
        provider="KISOptionRestAdapter",
        schema_version="canonical-market-observation-v1",
        run_id="run-1",
        contract=OptionInstrumentIdentity(
            instrument_id=symbol, symbol=symbol, expiry="20261008",
            option_type=option_type, strike=Decimal(str(strike)),
            contract_multiplier=Decimal("250000"),
        ),
        quote=MarketQuote(last=Decimal("10"), bid=Decimal("9.5"), ask=Decimal("10.5"), volume=Decimal("10")),
        order_book=MarketOrderBook(
            bids=tuple(OrderBookLevel(level=i, price=Decimal(str(9-i/10)), quantity=Decimal(str(100+i))) for i in range(1, 6)),
            asks=tuple(OrderBookLevel(level=i, price=Decimal(str(10+i/10)), quantity=Decimal(str(200+i))) for i in range(1, 6)),
            total_bid_quantity=Decimal("510"),
            total_ask_quantity=Decimal("1010"),
        ),
        analytics=MarketAnalytics(implied_volatility=iv),
        provenance=MarketDataProvenance(),
        underlying_price=Decimal("1110"),
        underlying_symbol="KOSPI200",
        underlying_source="kis_vts_rest",
    )


def test_historical_observation_option_source_never_looks_ahead():
    t1 = datetime(2026, 9, 22, 4, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 22, 4, 1, tzinfo=timezone.utc)
    source = HistoricalObservationOptionSource([_observation("B1", "CALL", 1090, t1, Decimal("0.21")),
                                                _observation("B1", "CALL", 1090, t2, Decimal("0.35"))])
    source.set_as_of(t1)
    assert source.get_iv(expiry="20261008", option_type="CALL", strike=Decimal("1090")) == Decimal("0.21")
    assert source.get_order_book("B1").bid_quantities == (Decimal("101"), Decimal("102"), Decimal("103"), Decimal("104"), Decimal("105"))
    source.set_as_of(t2)
    assert source.get_iv(expiry="20261008", option_type="CALL", strike=Decimal("1090")) == Decimal("0.35")
