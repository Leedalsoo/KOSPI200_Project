from decimal import Decimal

from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from contracts.types import ExecutionLeg, MultiLegExecutionPlan
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick
from environments.virtual.market.historical_market_store import HistoricalMarketStore
from tests.unit.test_historical_replay_multi_leg_execution import _bundle


def test_virtual_fill_position_grouped_pnl_preserves_authoritative_multiplier_and_identity(tmp_path):
    bundle = _bundle(tmp_path)
    store = HistoricalMarketStore(tmp_path / "grouped-position-events.jsonl")
    events = (
        ("CALL", 510.0, "201S11305", 3.20, 3.30, 3.25, 20),
        ("PUT", 510.0, "201S11306", 2.70, 2.80, 2.80, 21),
    )
    for idx, (option_type, strike, symbol, bid, ask, last, seq) in enumerate(events):
        store.append(ReferenceCanonicalMarketTick(
            timestamp=f"2026-10-15T10:00:00.{123 + idx:03d}",
            underlying_price=512.5, strike_price=strike, option_type=option_type,
            contract_multiplier=250000.0, bid_price=bid, ask_price=ask,
            last_price=last, volume=100, seq_id=seq, expiry="202610", symbol=symbol,
        ), source="KIS:H0IOCNT0")
    bundle.market.load_historical_store(store, source="KIS:H0IOCNT0")
    for _ in events:
        assert bundle.market.replay_next() is not None

    bridge = VirtualMultiLegExecutionBridge(bundle=bundle, run_id="TEST-RUN", option_master=bundle.option_master)
    plan = MultiLegExecutionPlan(
        group_id="GROUP-POSITION-PROV-1",
        strategy_id="STRATEGY-POSITION-PROV-1",
        purpose="GROUPED_POSITION_PNL_PROVENANCE",
        legs=(
            ExecutionLeg("call", "BUY", 1, "CALL", Decimal("510")),
            ExecutionLeg("put", "SELL", 1, "PUT", Decimal("510")),
        ),
    )
    result = bridge.execute(plan)

    assert result.group_complete is True
    assert len(result.reports) == 2
    assert set(bridge.leg_positions) == {"201S11305", "201S11306"}
    for instrument_id, position in bridge.leg_positions.items():
        state = position.snapshot()[instrument_id]
        assert state.contract_multiplier == Decimal("250000")
        assert state.identity_source == "OPTION_MASTER"

    snapshot = bridge.position_groups.snapshot(plan.group_id)
    assert snapshot is not None and snapshot.complete is True
    assert {leg.instrument_id for leg in snapshot.legs} == {"201S11305", "201S11306"}
    assert all(leg.contract_multiplier == Decimal("250000") for leg in snapshot.legs)
    assert all(leg.identity_source == "OPTION_MASTER" for leg in snapshot.legs)
    assert snapshot.total_pnl == -37500.0
