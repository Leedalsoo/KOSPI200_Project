from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from contracts.position_provenance import PositionRole
from contracts.types import ExecutionFill, ExecutionLeg, ExecutionReport, MultiLegExecutionPlan, OptionInstrumentIdentity
from environments.virtual.authoritative_vssf.track9_fee_ledger import VirtualTrack9FeeLedger
from environments.virtual.position.virtual_position_lot_store import VirtualPositionLotStore


def _bridge():
    bridge = object.__new__(VirtualMultiLegExecutionBridge)
    bridge.run_id = "S8-MULTI-PARTIAL-RUN"
    bridge.execution_legs = {}
    bridge.provenance = {}
    bridge.leg_positions = {}
    bridge._applied_execution_fingerprints = {}
    bridge.position_lot_store = VirtualPositionLotStore()
    bridge.fee_ledger = VirtualTrack9FeeLedger()
    return bridge


def _inputs():
    identity = OptionInstrumentIdentity(
        "SYNTHETIC-CALL-20261119-500", "SYNTHETIC-CALL-20261119-500",
        "20261119", "CALL", Decimal("500"), Decimal("250000"),
        "SYNTHETIC_VALIDATION_ONLY",
    )
    leg = SimpleNamespace(leg_id="call", side="BUY", position_role=PositionRole.NONE.value)
    plan = MultiLegExecutionPlan(
        group_id="S8-MULTI-PARTIAL-GROUP",
        strategy_id="track8_macro_regime_monthly_strangle",
        purpose="S8_MULTI_PARTIAL_FILL",
        legs=(ExecutionLeg(
            "call", "BUY", 5, option_type="CALL",
            strike=Decimal("500"), instrument_identity=identity,
        ),),
    )
    command = SimpleNamespace(
        client_order_id="S8-MULTI-PARTIAL-ORDER",
        instrument_id=identity.instrument_id,
        side="BUY",
        instrument_identity=identity,
    )
    fills = (
        ExecutionFill(
            "S8-FILL-001", 1, Decimal("10.00"),
            datetime(2026, 11, 3, 9, 2), Decimal("0.10"),
        ),
        ExecutionFill(
            "S8-FILL-002", 2, Decimal("11.00"),
            datetime(2026, 11, 3, 9, 4), Decimal("0.20"),
        ),
    )
    report = ExecutionReport(
        client_order_id=command.client_order_id,
        broker_order_id=command.client_order_id,
        execution_id=None,
        status="CANCELLED",
        filled_quantity=3,
        remaining_quantity=2,
        execution_price=Decimal("10.66666666666666666666666667"),
        execution_timestamp=datetime(2026, 11, 3, 9, 4),
        fee=Decimal("0.30"),
        group_id=plan.group_id,
        leg_id=leg.leg_id,
        execution_fills=fills,
    )
    return plan, leg, identity, command, report


def test_bridge_applies_each_partial_execution_to_distinct_position_lots_and_fee_rows():
    bridge = _bridge()
    plan, leg, identity, command, report = _inputs()

    bridge._apply_reconciled_execution(
        plan=plan, leg=leg, identity=identity,
        broker_command=command, report=report,
    )

    lots = bridge.position_lot_store.open_lots()
    assert [(lot.execution_id, lot.opened_quantity) for lot in lots] == [
        ("S8-FILL-001", 1),
        ("S8-FILL-002", 2),
    ]
    assert all(lot.client_order_id == command.client_order_id for lot in lots)
    assert all(lot.group_id == plan.group_id and lot.leg_id == leg.leg_id for lot in lots)
    assert bridge.leg_positions[identity.instrument_id].qty == 3
    assert bridge.leg_positions[identity.instrument_id].avg_price == pytest.approx(10.6666666667)
    assert bridge.fee_ledger.total(run_id=bridge.run_id) == Decimal("0.30")
    assert set(bridge.execution_legs) == {"S8-FILL-001", "S8-FILL-002"}


def test_repeated_cumulative_report_is_idempotent_by_execution_id():
    bridge = _bridge()
    plan, leg, identity, command, report = _inputs()

    for _ in range(2):
        bridge._apply_reconciled_execution(
            plan=plan, leg=leg, identity=identity,
            broker_command=command, report=report,
        )

    assert len(bridge.position_lot_store.history()) == 2
    assert bridge.leg_positions[identity.instrument_id].qty == 3
    assert len(bridge.fee_ledger.query(run_id=bridge.run_id)) == 2
    assert bridge.fee_ledger.total(run_id=bridge.run_id) == Decimal("0.30")


def test_conflicting_reused_execution_id_fails_closed_without_new_lot():
    bridge = _bridge()
    plan, leg, identity, command, report = _inputs()
    bridge._apply_reconciled_execution(
        plan=plan, leg=leg, identity=identity,
        broker_command=command, report=report,
    )
    conflicting_fill = ExecutionFill(
        "S8-FILL-001", 1, Decimal("10.25"),
        datetime(2026, 11, 3, 9, 2), Decimal("0.10"),
    )
    conflicting = replace(
        report,
        execution_fills=(conflicting_fill, report.execution_fills[1]),
    )

    with pytest.raises(RuntimeError, match="MULTI_LEG_EXECUTION_ID_CONFLICT_RECONCILIATION_REQUIRED"):
        bridge._apply_reconciled_execution(
            plan=plan, leg=leg, identity=identity,
            broker_command=command, report=conflicting,
        )

    assert len(bridge.position_lot_store.history()) == 2
    assert bridge.leg_positions[identity.instrument_id].qty == 3
