from decimal import Decimal
import pytest

from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from contracts.types import ExecutionLeg, MultiLegExecutionPlan
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick
from environments.virtual.market.historical_market_store import HistoricalMarketStore
from tests.unit.test_historical_replay_multi_leg_execution import _bundle
from tests.risk_guard_test_support import allow_risk_guard
from core.option.option_master import KisOptionContractIdentity


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
            last_price=last, volume=100, seq_id=seq, expiry="20261015", symbol=symbol,
        ), source="KIS:H0IOCNT0")
    bundle.market.load_historical_store(store, source="KIS:H0IOCNT0")
    for _ in events:
        assert bundle.market.replay_next() is not None

    bridge = VirtualMultiLegExecutionBridge(bundle=bundle, run_id="TEST-RUN", option_master=bundle.option_master, risk_guard_status_source=allow_risk_guard())
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
    assert snapshot.realized_pnl == 0.0
    assert snapshot.unrealized_pnl == -37500.0
    assert snapshot.total_pnl == -37500.0



def test_position_group_snapshot_uses_authoritative_realized_pnl_for_closed_option_leg(tmp_path):
    bundle = _bundle(tmp_path)
    bundle.option_master.register_contract_identity(
        KisOptionContractIdentity(
            shrn_iscd="C01610A34", stnd_iscd="KR4101S11334", expiry="2026-10-15",
            option_type="CALL", strike=Decimal("610"), info_type="5",
            contract_multiplier=Decimal("250000"),
        )
    )
    store = HistoricalMarketStore(tmp_path / "closed-option-events.jsonl")
    tick = ReferenceCanonicalMarketTick(
        timestamp="2026-10-15T10:00:01.123", underlying_price=512.5,
        strike_price=610.0, option_type="CALL", contract_multiplier=250000.0,
        bid_price=23.35, ask_price=23.40, last_price=24.70, volume=100,
        seq_id=19, expiry="20261015", symbol="C01610A34",
    )
    store.append(tick, source="KIS:H0IOCNT0")
    bundle.market.load_historical_store(store, source="KIS:H0IOCNT0")
    assert bundle.market.replay_next() is not None

    vssf = bundle.execution._authoritative_execute.__self__.vssf_runtime
    vssf.account.position_mgr.positions["C01610A34"] = {
        "qty": 1, "avg_price": 24.50, "side": "BUY"
    }

    bridge = VirtualMultiLegExecutionBridge(
        bundle=bundle, run_id="TEST-CLOSED-RUN", option_master=bundle.option_master,
        risk_guard_status_source=allow_risk_guard()
    )
    plan = MultiLegExecutionPlan(
        group_id="GROUP-CLOSED-REALIZED-1", strategy_id="STRATEGY-CLOSED-REALIZED-1",
        purpose="AUTHORITATIVE_REALIZED_PNL",
        legs=(ExecutionLeg("close", "SELL", 1, "CALL", Decimal("610")),),
    )
    result = bridge.execute(plan)
    assert result.group_complete is True
    assert result.reports[0].execution_price == 23.35
    snapshot = bridge.position_groups.snapshot(plan.group_id)
    assert snapshot is not None
    assert snapshot.realized_pnl == pytest.approx(-287500.0, abs=0.01)
    assert snapshot.unrealized_pnl == 0.0
    assert snapshot.total_pnl == pytest.approx(-287500.0, abs=0.01)