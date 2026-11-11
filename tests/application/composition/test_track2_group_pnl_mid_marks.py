from datetime import datetime
from pathlib import Path
from decimal import Decimal
from types import SimpleNamespace

import pytest

from core.oms.position_group import (
    LegStatus,
    PositionGroup,
    PositionGroupLeg,
    PositionGroupLegPnL,
    PositionGroupRegistry,
    PositionGroupSnapshot,
)
from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from contracts.types import OptionInstrumentIdentity
from core.strategy.track2_asymmetric_trap import Track2AsymmetricTrap


GROUP_ID = "S2-MID-GROUP"
STRATEGY_ID = "track2_asymmetric_trap"
RUN_ID = "S2-MID-RUN"
OBSERVED_AT = "2026-10-21T13:38:16.270369+09:00"


def _bridge_with_track2_group(*, omit_quote=None):
    bridge = object.__new__(VirtualMultiLegExecutionBridge)
    bridge.run_id = RUN_ID
    bridge.position_groups = PositionGroupRegistry()
    contracts = (
        ("inner_put", "C01611877", "SELL", Decimal("877.5"), "PUT", Decimal("35.90"), Decimal("39.05")),
        ("outer_put", "C01611882", "BUY", Decimal("882.5"), "PUT", Decimal("38.15"), Decimal("41.75")),
        ("inner_call", "B01611887", "SELL", Decimal("887.5"), "CALL", Decimal("39.20"), Decimal("41.25")),
        ("outer_call", "B01611892", "BUY", Decimal("892.5"), "CALL", Decimal("36.70"), Decimal("38.40")),
    )
    group_legs = tuple(
        PositionGroupLeg(
            leg_id, GROUP_ID, instrument_id, side, 1, Decimal("250000"),
            "KIS_OFFICIAL_INDEX_MASTER:EXACT_DATE", LegStatus.FILLED,
        )
        for leg_id, instrument_id, side, _strike, _kind, _bid, _ask in contracts
    )
    bridge.position_groups.register(PositionGroup(GROUP_ID, STRATEGY_ID, "MULTI_LEG", group_legs))
    pnl_legs = tuple(
        PositionGroupLegPnL(
            leg_id, GROUP_ID, instrument_id, 1, Decimal("250000"),
            "KIS_OFFICIAL_INDEX_MASTER:EXACT_DATE", 40.0, 99.0, 0.0,
            RUN_ID, f"client-{leg_id}", f"exec-{leg_id}", (f"exec-{leg_id}",),
        )
        for leg_id, instrument_id, _side, _strike, _kind, _bid, _ask in contracts
    )
    bridge.position_groups.update_snapshot(
        PositionGroupSnapshot(GROUP_ID, STRATEGY_ID, True, pnl_legs, 125.0, 0.0, 125.0)
    )
    positions = {
        instrument_id: {
            "qty": 1, "avg_price": 40.0, "side": side, "mark_price": 99.0,
        }
        for _leg_id, instrument_id, side, _strike, _kind, _bid, _ask in contracts
    }
    quotes = {
        instrument_id: {
            "bid": float(bid), "ask": float(ask), "timestamp": OBSERVED_AT,
        }
        for _leg_id, instrument_id, _side, _strike, _kind, bid, ask in contracts
    }
    if omit_quote:
        quotes.pop(omit_quote)
    owner = SimpleNamespace(vssf_runtime=SimpleNamespace(account=SimpleNamespace(positions=positions)))
    bridge.bundle = SimpleNamespace(
        execution=SimpleNamespace(_authoritative_execute=SimpleNamespace(__self__=owner)),
        market=SimpleNamespace(option_quotes_by_instrument_id=quotes),
    )
    return bridge


def test_track2_group_refresh_uses_bid_ask_mid_and_preserves_quote_provenance():
    bridge = _bridge_with_track2_group()

    assert bridge.refresh_position_group_marks() == 1

    snapshot = bridge.position_groups.snapshot(GROUP_ID)
    expected = {
        "C01611877": 37.475,
        "C01611882": 39.95,
        "B01611887": 40.225,
        "B01611892": 37.55,
    }
    for leg in snapshot.legs:
        assert leg.current_price == pytest.approx(expected[leg.instrument_id])
        assert leg.mark_source == "BID_ASK_MID"
        assert leg.quote_observed_at == datetime.fromisoformat(OBSERVED_AT)
        assert leg.quote_bid > 0
        assert leg.quote_ask >= leg.quote_bid
    assert snapshot.realized_pnl == pytest.approx(125.0)
    assert snapshot.net_pnl is None


def test_track2_group_refresh_fails_closed_without_one_leg_quote_and_is_atomic():
    bridge = _bridge_with_track2_group(omit_quote="B01611892")
    before = bridge.position_groups.snapshot(GROUP_ID)

    with pytest.raises(ValueError, match="TRACK2_GROUP_PNL_QUOTE_REQUIRED"):
        bridge.refresh_position_group_marks()

    assert bridge.position_groups.snapshot(GROUP_ID) == before


def test_track2_mid_quote_rejects_crossed_or_untimestamped_quotes():
    with pytest.raises(ValueError, match="TRACK2_GROUP_PNL_MID_BID_ASK_INVALID"):
        VirtualMultiLegExecutionBridge._track2_mid_quote(
            {"bid": "41.0", "ask": "40.0", "timestamp": OBSERVED_AT}, "OPT-X"
        )
    with pytest.raises(ValueError, match="TRACK2_GROUP_PNL_QUOTE_TIMESTAMP_REQUIRED"):
        VirtualMultiLegExecutionBridge._track2_mid_quote(
            {"bid": "40.0", "ask": "41.0"}, "OPT-X"
        )


def test_track2_fee_total_is_unknown_when_any_filled_report_lacks_fee_evidence():
    known = SimpleNamespace(
        filled_quantity=1, execution_id="EXEC-1", client_order_id="CLIENT-1",
        fee=Decimal("12.5"), execution_fills=(),
    )
    missing = SimpleNamespace(
        filled_quantity=1, execution_id="EXEC-2", client_order_id="CLIENT-2",
        fee=None, execution_fills=(),
    )
    assert VirtualMultiLegExecutionBridge._track2_fee_total((known,)) == Decimal("12.5")
    assert VirtualMultiLegExecutionBridge._track2_fee_total((known, missing)) is None



def test_track2_terminal_snapshot_keeps_mid_marks_for_remaining_open_legs():
    bridge = _bridge_with_track2_group()
    bridge.position_lot_store = SimpleNamespace(open_lots=lambda: tuple(
        SimpleNamespace(
            run_id=RUN_ID, strategy_id=STRATEGY_ID, group_id=GROUP_ID,
            instrument_id=instrument_id, remaining_quantity=1,
        )
        for instrument_id in ("C01611877", "C01611882", "B01611887", "B01611892")
    ))
    bridge.provenance = {}
    bridge.refresh_position_group_marks()
    previous = bridge.position_groups.snapshot(GROUP_ID)
    plan = SimpleNamespace(strategy_id=STRATEGY_ID, group_id=GROUP_ID)

    updated = bridge._build_terminal_position_group_snapshot(
        plan=plan, previous=previous, realized_delta=Decimal("5"), reports=(),
    )

    assert updated.realized_pnl == pytest.approx(130.0)
    assert all(leg.mark_source == "BID_ASK_MID" for leg in updated.legs)
    assert all(leg.quote_observed_at == datetime.fromisoformat(OBSERVED_AT) for leg in updated.legs)
    assert updated.net_pnl is None


def test_track2_close_plan_is_built_from_the_existing_four_authoritative_open_lots():
    bridge = object.__new__(VirtualMultiLegExecutionBridge)
    bridge.run_id = RUN_ID
    source = (
        ("C01611877", "PUT", "877.5", "SELL"),
        ("C01611882", "PUT", "882.5", "BUY"),
        ("B01611887", "CALL", "887.5", "SELL"),
        ("B01611892", "CALL", "892.5", "BUY"),
    )
    lots = []
    for instrument_id, option_type, strike, side in source:
        identity = OptionInstrumentIdentity(
            instrument_id=instrument_id, symbol=instrument_id, expiry="20261112",
            option_type=option_type, strike=Decimal(strike),
            contract_multiplier=Decimal("250000"),
            identity_source="KIS_OFFICIAL_INDEX_MASTER:EXACT_DATE",
        )
        lots.append(SimpleNamespace(
            run_id=RUN_ID, strategy_id=STRATEGY_ID, group_id=GROUP_ID,
            instrument_id=instrument_id, remaining_quantity=1,
            instrument_identity=identity, position_role="OPTION_LEG", side=side,
        ))
    bridge.position_lot_store = SimpleNamespace(open_lots=lambda: tuple(lots))

    plan = bridge.build_close_plan_from_open_lots(
        strategy_id=STRATEGY_ID, purpose="TRAP_CLOSE", asset_type="OPTION",
    )

    assert plan.group_id == GROUP_ID
    assert plan.strategy_id == STRATEGY_ID
    assert plan.purpose == "TRAP_CLOSE"
    assert len(plan.legs) == 4
    assert {leg.side for leg in plan.legs} == {"BUY", "SELL"}
    assert bridge._is_terminal_execution_plan(plan) is True



def _strategy_group_pnl_snapshot(*, net_pnl=-40.0, slippage=2.0, quote_freshness_verified=True):
    legs = tuple(SimpleNamespace(
        mark_source="BID_ASK_MID", quote_bid=35.0, quote_ask=36.0,
        quote_observed_at=datetime.fromisoformat(OBSERVED_AT),
    ) for _ in range(4))
    return SimpleNamespace(
        strategy_id=STRATEGY_ID, complete=True, legs=legs,
        initial_net_premium_received=100.0, fees=5.0, slippage=slippage,
        net_pnl=net_pnl, quote_freshness_verified=quote_freshness_verified,
    )


def test_track2_group_exit_stays_blocked_until_cost_freshness_and_exit_policy_are_resolved():
    strategy = Track2AsymmetricTrap()
    strategy._trap_active = True
    strategy.update_group_pnl_snapshot(_strategy_group_pnl_snapshot())

    assert strategy._group_pnl_status == "GROUP_PNL_EXIT_POLICY_UNRESOLVED"
    assert strategy.evaluate_trap(Decimal("885.93"), datetime.fromisoformat(OBSERVED_AT)) == ()

    strategy.update_group_pnl_snapshot(_strategy_group_pnl_snapshot(slippage=None))
    assert strategy._group_pnl_status == "GROUP_PNL_COST_EVIDENCE_MISSING"
    assert strategy.evaluate_trap(Decimal("885.93"), datetime.fromisoformat(OBSERVED_AT)) == ()

    strategy.update_group_pnl_snapshot(_strategy_group_pnl_snapshot(quote_freshness_verified=None))
    assert strategy._group_pnl_status == "GROUP_PNL_QUOTE_FRESHNESS_POLICY_UNRESOLVED"
    assert strategy.evaluate_trap(Decimal("885.93"), datetime.fromisoformat(OBSERVED_AT)) == ()


def test_track2_group_stop_exit_builds_trap_close_signal_when_test_policy_is_injected():
    strategy = Track2AsymmetricTrap()
    strategy._trap_active = True
    # Test-only policy values exercise the route; production defaults remain unresolved.
    strategy.STOP_LOSS_RATIO = Decimal("-0.30")
    strategy.TRAILING_ACTIVATION_RATIO = Decimal("0.30")
    strategy.TRAILING_PULLBACK_RATIO = Decimal("0.20")
    strategy.update_group_pnl_snapshot(_strategy_group_pnl_snapshot(net_pnl=-40.0))

    signals = strategy.evaluate_trap(Decimal("885.93"), datetime.fromisoformat(OBSERVED_AT))

    assert len(signals) == 1
    assert signals[0].execution_proposal.tag_id == "TRAP_CLOSE"
    assert "STOP_LOSS" in signals[0].reason


def test_track2_runtime_tick_processor_refreshes_group_pnl_before_strategy_evaluation():
    import ast
    source = Path("application/composition/automated_virtual_runtime_factory.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    processor = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "process_pending_multi_leg"
    )
    calls = {
        node.func.attr
        for node in ast.walk(processor)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "refresh_position_group_marks" in calls
    assert "update_group_pnl_snapshot" in calls
    assert "update_group_pnl_status" in calls
