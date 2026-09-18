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
    assert bridge.fee_ledger.total(run_id="RUNTIME-PROV-1") == Decimal("0")
    assert len(bridge.fee_ledger.query(run_id="RUNTIME-PROV-1")) == 2


def test_repeated_bridge_executions_consume_fifo_and_create_reversal_lot(tmp_path):
    bundle = _bundle(tmp_path)
    store = HistoricalMarketStore(tmp_path / "repeat-events.jsonl")
    store.append(ReferenceCanonicalMarketTick(
        timestamp="2026-10-15T10:00:00.001", underlying_price=512.5,
        strike_price=510.0, option_type="CALL", contract_multiplier=250000.0,
        bid_price=3.20, ask_price=3.30, last_price=3.25, volume=100, seq_id=1,
        expiry="202610", symbol="201S11305",
    ), source="KIS:H0IOCNT0")
    bundle.market.load_historical_store(store, source="KIS:H0IOCNT0")
    assert bundle.market.replay_next() is not None
    bridge = VirtualMultiLegExecutionBridge(
        bundle=bundle, run_id="RUNTIME-FIFO-1", option_master=bundle.option_master
    )

    def execute(group, side, qty, strategy, role=PositionRole.NONE):
        plan = MultiLegExecutionPlan(
            group_id=group, strategy_id=strategy,
            legs=(ExecutionLeg("call", side, qty, "CALL", Decimal("510"), position_role=role),),
        )
        return bridge.execute(plan)

    first = execute("G1", "BUY", 2, "S1", PositionRole.OVERNIGHT_INSURANCE)
    second = execute("G2", "BUY", 3, "S2")
    close = execute("G3", "SELL", 4, "S3")
    assert [x.execution_id for x in bridge.position_lot_store.open_lots()] == [second.reports[0].execution_id]
    residual = bridge.position_lot_store.open_lots()[0]
    assert residual.remaining_quantity == 1
    assert residual.strategy_id == "S2"
    assert residual.group_id == "G2"
    assert residual.position_role == PositionRole.NONE
    assert bridge.position_lot_store.close_events()[0].source_lot_execution_id == first.reports[0].execution_id
    assert bridge.position_lot_store.close_events()[1].source_lot_execution_id == second.reports[0].execution_id

    reversal = execute("G4", "SELL", 3, "S4", PositionRole.EVENT_INSURANCE)
    lots = bridge.position_lot_store.open_lots()
    assert len(lots) == 1
    new_lot = lots[0]
    assert new_lot.execution_id == reversal.reports[0].execution_id
    assert new_lot.strategy_id == "S4"
    assert new_lot.group_id == "G4"
    assert new_lot.leg_id == "call"
    assert new_lot.remaining_quantity == 2
    assert new_lot.position_role == PositionRole.EVENT_INSURANCE
    assert all(x.execution_id != second.reports[0].execution_id for x in lots)
    assert bridge.position_lot_store.close_events()[2].source_lot_execution_id == second.reports[0].execution_id
    assert bridge.insurance_position.snapshot()[0].execution_id == reversal.reports[0].execution_id