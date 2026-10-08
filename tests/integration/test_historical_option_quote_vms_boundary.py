from datetime import datetime, timezone
from decimal import Decimal

from contracts.types import (
    MarketAnalytics, MarketDataProvenance, MarketObservation, MarketOrderBook,
    MarketQuote, OptionInstrumentIdentity, OrderBookLevel,
)
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick
from environments.virtual.market.simulator_runtime import VirtualMarketSimulatorRuntime
from infrastructure.kis.historical_observation_sources import HistoricalObservationOptionSource


def _observation(*, symbol: str, option_type: str, strike: str) -> MarketObservation:
    now = datetime(2026, 10, 1, 23, 29, 15, tzinfo=timezone.utc)
    levels_bid = tuple(OrderBookLevel(i, Decimal('3.00') + Decimal(i) / 100, Decimal('10')) for i in range(1, 6))
    levels_ask = tuple(OrderBookLevel(i, Decimal('3.20') + Decimal(i) / 100, Decimal('10')) for i in range(1, 6))
    return MarketObservation(
        observation_id=f'{symbol}-OBS', observed_at=now, collected_at=now,
        source='kis_vts_rest', provider='test', schema_version='test', run_id='RUN-TEST',
        contract=OptionInstrumentIdentity(
            instrument_id=symbol, symbol=symbol, expiry='2026-10-08',
            option_type=option_type, strike=Decimal(strike), contract_multiplier=Decimal('250000'),
            identity_source='OPTION_MASTER',
        ),
        quote=MarketQuote(last=Decimal('3.10'), bid=Decimal('3.00'), ask=Decimal('3.20')),
        order_book=MarketOrderBook(bids=levels_bid, asks=levels_ask),
        analytics=MarketAnalytics(), provenance=MarketDataProvenance(),
    )


def test_historical_quote_boundary_does_not_invent_missing_call_and_vms_stays_fail_closed():
    source = HistoricalObservationOptionSource([
        _observation(symbol='C01610A40', option_type='PUT', strike='1092.5'),
    ])
    vms = VirtualMarketSimulatorRuntime()
    vms.set_authoritative_option_quote_provider(source.latest_authoritative_option_quotes)

    tick = ReferenceCanonicalMarketTick(
        timestamp='2026-10-01T23:29:16.000000+00:00', underlying_price=1105.0,
        strike_price=1090.0, option_type='CALL', contract_multiplier=250000,
        bid_price=1.0, ask_price=1.2, last_price=1.1, seq_id=1,
        expiry='202610', symbol='B01610A32',
    )
    vms.publish_replay_tick(tick)
    quotes = vms.option_quotes

    assert ('PUT', 1092.5, '20261008') in quotes
    assert ('CALL', 1117.5, '20261008') not in quotes

    # The execution boundary must remain fail-closed when the authoritative pair is incomplete.
    assert all(
        not (key[0] == 'CALL' and key[1] == 1117.5 and key[2] == '20261008')
        for key in quotes
    )
