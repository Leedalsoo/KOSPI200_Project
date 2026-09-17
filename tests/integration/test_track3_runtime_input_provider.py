from datetime import datetime, timezone

from application.composition.track3_runtime_input_provider import Track3RuntimeInputProvider
from contracts.track3_runtime_input_source import Track3RuntimeInput
from contracts.types import CanonicalMarketTick, DataQuality, MarketState
from core.strategy.contracts import UnavailableStrategyPayload


class Source:
    def __init__(self, payload):
        self.payload = payload

    def get_input(self, symbol, observed_at):
        return self.payload


def market_state():
    observed_at = datetime(2026, 9, 17, 1, 0, tzinfo=timezone.utc)
    tick = CanonicalMarketTick("TEST-OPTION", observed_at, 2.5)
    return MarketState(
        as_of=observed_at,
        ticks={tick.instrument_id: tick},
        quality={tick.instrument_id: DataQuality(True, True, True)},
    )


def payload(state):
    return Track3RuntimeInput(
        observed_at=state.as_of,
        spread_history=tuple(float(x) for x in range(1, 11)),
        active_vol=0.12,
        base_vol=0.10,
        price_change_rate=0.01,
        bid_ask_spread=0.02,
        gap_pct=0.0,
        is_gap=False,
        market_stable=True,
        spread_normalizing=True,
        allow_size_up=False,
        total_fees=1500.0,
        premium_spent=25000.0,
        options_legs=(
            {"strike": 2.5, "price": 0.12, "qty": 1, "side": "BUY", "type": "CALL", "contract_multiplier": 250000.0},
        ),
        contract_multiplier=250000.0,
        source="VirtualBroker.position_fee_premium_ledger",
    )


def test_missing_source_is_fail_closed():
    context = Track3RuntimeInputProvider().build(market_state())
    assert isinstance(context.input.payload, UnavailableStrategyPayload)
    assert context.input.data_status["fee_ledger"] == "UNAVAILABLE"


def test_authoritative_source_materializes_track3_payload():
    state = market_state()
    context = Track3RuntimeInputProvider(Source(payload(state))).build(state)
    data = context.input.payload
    assert data.spread_history == tuple(float(x) for x in range(1, 11))
    assert data.active_vol == 0.12
    assert data.base_vol == 0.10
    assert data.total_fees == 1500.0
    assert data.premium_spent == 25000.0
    assert data.options_legs[0]["strike"] == 2.5
    assert data.options_legs[0]["contract_multiplier"] == 250000.0
    assert data.contract_multiplier == 250000.0
    assert context.input.data_status["source"] == "VirtualBroker.position_fee_premium_ledger"


def test_missing_contract_multiplier_is_blocked():
    state = market_state()
    source_payload = payload(state)
    source_payload = Track3RuntimeInput(
        observed_at=source_payload.observed_at,
        spread_history=source_payload.spread_history,
        active_vol=source_payload.active_vol,
        base_vol=source_payload.base_vol,
        price_change_rate=source_payload.price_change_rate,
        bid_ask_spread=source_payload.bid_ask_spread,
        gap_pct=source_payload.gap_pct,
        is_gap=source_payload.is_gap,
        market_stable=source_payload.market_stable,
        spread_normalizing=source_payload.spread_normalizing,
        allow_size_up=source_payload.allow_size_up,
        total_fees=source_payload.total_fees,
        premium_spent=source_payload.premium_spent,
        options_legs=source_payload.options_legs,
        contract_multiplier=None,
        source=source_payload.source,
    )
    context = Track3RuntimeInputProvider(Source(source_payload)).build(state)
    assert isinstance(context.input.payload, UnavailableStrategyPayload)


def test_stale_authoritative_payload_is_blocked():
    state = market_state()
    stale = payload(state)
    stale = Track3RuntimeInput(
        observed_at=state.as_of.replace(minute=59),
        spread_history=stale.spread_history,
        active_vol=stale.active_vol,
        base_vol=stale.base_vol,
        price_change_rate=stale.price_change_rate,
        bid_ask_spread=stale.bid_ask_spread,
        gap_pct=stale.gap_pct,
        is_gap=stale.is_gap,
        market_stable=stale.market_stable,
        spread_normalizing=stale.spread_normalizing,
        allow_size_up=stale.allow_size_up,
        total_fees=stale.total_fees,
        premium_spent=stale.premium_spent,
        options_legs=stale.options_legs,
        contract_multiplier=stale.contract_multiplier,
        source=stale.source,
    )
    context = Track3RuntimeInputProvider(Source(stale)).build(state)
    assert isinstance(context.input.payload, UnavailableStrategyPayload)
