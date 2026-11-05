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


def _bridge_with_group(positions):
    bridge = object.__new__(VirtualMultiLegExecutionBridge)
    bridge.run_id = "S8-MTM-TEST-RUN"
    bridge.position_groups = PositionGroupRegistry()
    group_id = "S8-MTM-TEST-GROUP"
    strategy_id = "track8_macro_regime_monthly_strangle"
    legs = (
        PositionGroupLeg(
            "call", group_id, "SYNTHETIC-CALL", "BUY", 3,
            Decimal("250000"), "SYNTHETIC_VALIDATION_ONLY", LegStatus.FILLED,
        ),
        PositionGroupLeg(
            "put", group_id, "SYNTHETIC-PUT", "SELL", 2,
            Decimal("250000"), "SYNTHETIC_VALIDATION_ONLY", LegStatus.FILLED,
        ),
    )
    bridge.position_groups.register(
        PositionGroup(group_id, strategy_id, "MULTI_LEG", legs)
    )
    snapshot_legs = (
        PositionGroupLegPnL(
            "call", group_id, "SYNTHETIC-CALL", 3, Decimal("250000"),
            "SYNTHETIC_VALIDATION_ONLY", 10.0, 10.0, 0.0,
            bridge.run_id, "CALL-ORDER", "CALL-EXEC", ("CALL-EXEC",),
        ),
        PositionGroupLegPnL(
            "put", group_id, "SYNTHETIC-PUT", 2, Decimal("250000"),
            "SYNTHETIC_VALIDATION_ONLY", 8.0, 8.0, 0.0,
            bridge.run_id, "PUT-ORDER", "PUT-EXEC", ("PUT-EXEC",),
        ),
    )
    bridge.position_groups.update_snapshot(
        PositionGroupSnapshot(
            group_id, strategy_id, True, snapshot_legs,
            125.0, 0.0, 125.0,
        )
    )
    account = SimpleNamespace(positions=positions)
    vssf_runtime = SimpleNamespace(account=account)
    execution_owner = SimpleNamespace(vssf_runtime=vssf_runtime)
    bridge.bundle = SimpleNamespace(
        execution=SimpleNamespace(
            _authoritative_execute=SimpleNamespace(__self__=execution_owner)
        )
    )
    return bridge, group_id


def test_refresh_position_group_marks_reconciles_each_open_leg_to_current_vssf_marks():
    bridge, group_id = _bridge_with_group(
        {
            "SYNTHETIC-CALL": {
                "qty": 2, "avg_price": 10.5, "side": "BUY", "mark_price": 12.5,
            },
            "SYNTHETIC-PUT": {
                "qty": 1, "avg_price": 8.0, "side": "SELL", "mark_price": 6.0,
            },
        }
    )

    assert bridge.refresh_position_group_marks() == 1

    snapshot = bridge.position_groups.snapshot(group_id)
    assert snapshot.realized_pnl == pytest.approx(125.0)
    assert snapshot.legs[0].quantity == 2
    assert snapshot.legs[0].avg_price == pytest.approx(10.5)
    assert snapshot.legs[0].current_price == pytest.approx(12.5)
    assert snapshot.legs[0].unrealized_pnl == pytest.approx(1_000_000.0)
    assert snapshot.legs[1].quantity == 1
    assert snapshot.legs[1].current_price == pytest.approx(6.0)
    assert snapshot.legs[1].unrealized_pnl == pytest.approx(500_000.0)
    assert snapshot.unrealized_pnl == pytest.approx(1_500_000.0)
    assert snapshot.total_pnl == pytest.approx(1_500_125.0)


def test_refresh_position_group_marks_zeroes_flat_leg_and_preserves_realized_pnl():
    bridge, group_id = _bridge_with_group(
        {
            "SYNTHETIC-CALL": {
                "qty": 2, "avg_price": 10.5, "side": "BUY", "mark_price": 12.5,
            },
        }
    )

    bridge.refresh_position_group_marks()

    snapshot = bridge.position_groups.snapshot(group_id)
    assert snapshot.legs[1].quantity == 0
    assert snapshot.legs[1].unrealized_pnl == 0.0
    assert snapshot.legs[1].current_price == 8.0
    assert snapshot.unrealized_pnl == pytest.approx(1_000_000.0)
    assert snapshot.realized_pnl == pytest.approx(125.0)


def test_refresh_position_group_marks_fails_closed_without_mark_and_does_not_partially_update():
    bridge, group_id = _bridge_with_group(
        {
            "SYNTHETIC-CALL": {
                "qty": 2, "avg_price": 10.5, "side": "BUY", "mark_price": 12.5,
            },
            "SYNTHETIC-PUT": {
                "qty": 1, "avg_price": 8.0, "side": "SELL",
            },
        }
    )
    before = bridge.position_groups.snapshot(group_id)

    with pytest.raises(ValueError, match="POSITION_GROUP_MTM_MARK_PRICE_REQUIRED"):
        bridge.refresh_position_group_marks()

    assert bridge.position_groups.snapshot(group_id) == before



def _terminal_lot(instrument_id, quantity):
    return SimpleNamespace(
        run_id="S8-MTM-TEST-RUN",
        strategy_id="track8_macro_regime_monthly_strangle",
        group_id="S8-MTM-TEST-GROUP",
        instrument_id=instrument_id,
        remaining_quantity=quantity,
    )


def test_terminal_close_accumulates_realized_pnl_and_preserves_entry_group_legs():
    bridge, group_id = _bridge_with_group({
        "SYNTHETIC-CALL": {
            "qty": 2, "avg_price": 10.5, "side": "BUY", "mark_price": 12.5,
        },
        "SYNTHETIC-PUT": {
            "qty": 1, "avg_price": 8.0, "side": "SELL", "mark_price": 6.0,
        },
    })
    bridge.position_lot_store = SimpleNamespace(open_lots=lambda: (
        _terminal_lot("SYNTHETIC-CALL", 2),
        _terminal_lot("SYNTHETIC-PUT", 1),
    ))
    bridge.provenance = {}
    plan = SimpleNamespace(group_id=group_id, strategy_id="track8_macro_regime_monthly_strangle")
    previous = bridge.position_groups.snapshot(group_id)

    updated = bridge._build_terminal_position_group_snapshot(
        plan=plan, previous=previous, realized_delta=Decimal("375"), reports=(),
    )

    assert updated.realized_pnl == pytest.approx(500.0)
    assert updated.unrealized_pnl == pytest.approx(1_500_000.0)
    assert updated.total_pnl == pytest.approx(1_500_500.0)
    assert [leg.leg_id for leg in updated.legs] == ["call", "put"]
    assert [leg.quantity for leg in updated.legs] == [2, 1]
    assert bridge.position_groups.get(group_id).legs[0].leg_id == "call"


def test_terminal_close_flat_state_zeroes_open_quantities_and_accumulates_realized_pnl_once():
    bridge, group_id = _bridge_with_group({})
    bridge.position_lot_store = SimpleNamespace(open_lots=lambda: ())
    bridge.provenance = {
        "CLOSE-CALL": {"instrument_id": "SYNTHETIC-CALL"},
        "CLOSE-PUT": {"instrument_id": "SYNTHETIC-PUT"},
    }
    plan = SimpleNamespace(group_id=group_id, strategy_id="track8_macro_regime_monthly_strangle")
    previous = bridge.position_groups.snapshot(group_id)
    reports = (
        SimpleNamespace(filled_quantity=3, execution_price=12.0, execution_id="CLOSE-CALL"),
        SimpleNamespace(filled_quantity=2, execution_price=6.0, execution_id="CLOSE-PUT"),
    )

    updated = bridge._build_terminal_position_group_snapshot(
        plan=plan, previous=previous, realized_delta=Decimal("500000"), reports=reports,
    )
    bridge.position_groups.update_snapshot(updated)

    assert updated.realized_pnl == pytest.approx(500125.0)
    assert updated.unrealized_pnl == pytest.approx(0.0)
    assert updated.total_pnl == pytest.approx(500125.0)
    assert [leg.quantity for leg in updated.legs] == [0, 0]
    assert [leg.unrealized_pnl for leg in updated.legs] == [0.0, 0.0]
    assert [leg.current_price for leg in updated.legs] == [12.0, 6.0]
    assert bridge._position_flat_for_plan(plan) is True


def test_terminal_reconciliation_fails_closed_when_position_lots_and_account_disagree():
    bridge, group_id = _bridge_with_group({
        "SYNTHETIC-CALL": {
            "qty": 2, "avg_price": 10.5, "side": "BUY", "mark_price": 12.5,
        },
    })
    bridge.position_lot_store = SimpleNamespace(open_lots=lambda: (
        _terminal_lot("SYNTHETIC-CALL", 1),
    ))
    bridge.provenance = {}
    plan = SimpleNamespace(group_id=group_id, strategy_id="track8_macro_regime_monthly_strangle")
    previous = bridge.position_groups.snapshot(group_id)

    with pytest.raises(ValueError, match="POSITION_GROUP_TERMINAL_LOT_ACCOUNT_QUANTITY_MISMATCH"):
        bridge._build_terminal_position_group_snapshot(
            plan=plan, previous=previous, realized_delta=Decimal("0"), reports=(),
        )
