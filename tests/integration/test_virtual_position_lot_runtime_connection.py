from decimal import Decimal

from contracts.position_provenance import PositionRole
from contracts.types import ExecutionLeg, MultiLegExecutionPlan
from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from tests.unit.test_historical_replay_multi_leg_execution import _bundle
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick
from environments.virtual.market.historical_market_store import HistoricalMarketStore


def test_virtual_multileg_execution_populates_track9_lot_read_models(tmp_path):
    bundle = _bundle(tmp_path)
    store = HistoricalMarketStore(tmp_path / "events.jsonl")
    for seq, option_type, symbol, bid, ask in (
        (1, "CALL", "201S11305", 3.20, 3.30),
        (2, "PUT", "201S11306", 2.70, 2.80),
    ):
        store.append(ReferenceCanonicalMarketTick(
            timestamp=f"2026-10-15T10:00:00.{seq:03d}",
            underlying_price=512.5, strike_price=510.0, option_type=option_type,
            contract_multiplier=250000.0, bid_price=bid, ask_price=ask,
            last_price=ask, volume=100, seq_id=seq, expiry="202610", symbol=symbol,
        ), source="KIS:H0IOCNT0")
    bundle.market.load_historical_store(store, source="KIS:H0IOCNT0")
    assert bundle.market.replay_next() is not None
    assert bundle.market.replay_next() is not None
    bridge = VirtualMultiLegExecutionBridge(
        bundle=bundle, run_id="RUNTIME-PROV-1", option_master=bundle.option_master
    )
    plan = MultiLegExecutionPlan(
        group_id="RUNTIME-PROV-G1", strategy_id="TRACK9",
        legs=(
            ExecutionLeg("call", "BUY", 2, "CALL", Decimal("510"), position_role=PositionRole.OVERNIGHT_INSURANCE),
            ExecutionLeg("put", "SELL", 1, "PUT", Decimal("510")),
        ),
    )
    result = bridge.execute(plan)
    assert result.group_complete is True
    lots = bridge.position_lot_store.open_lots()
    assert len(lots) == 2
    assert {lot.execution_id for lot in lots} == {r.execution_id for r in result.reports}
    assert all(lot.run_id == "RUNTIME-PROV-1" for lot in lots)
    assert all(lot.strategy_id == "TRACK9" for lot in lots)
    assert all(lot.group_id == plan.group_id for lot in lots)
    assert {lot.position_role for lot in lots} == {
        PositionRole.OVERNIGHT_INSURANCE, PositionRole.NONE
    }
    attributed = bridge.option_position_attribution.snapshot()
    insurance = bridge.insurance_position.snapshot()
    assert len(attributed) == 2
    assert len(insurance) == 1
    assert insurance[0].position_role == PositionRole.OVERNIGHT_INSURANCE
    assert insurance[0].remaining_quantity == 2
