from dataclasses import replace
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from application.composition.virtual_multi_leg_execution import VirtualMultiLegExecutionBridge
from contracts.position_provenance import PositionRole
from contracts.types import ExecutionFill, ExecutionLeg, ExecutionReport, MultiLegExecutionPlan, OptionInstrumentIdentity
from environments.virtual.authoritative_vssf.track9_fee_ledger import VirtualTrack9FeeLedger
from environments.virtual.position.virtual_position_lot_store import VirtualPositionLotStore
from application.composition.track2_u19_recovery import ValidationOnlyTrack2U19RecoveryCoordinator
from core.oms.track2_u19_recovery import (
    U19BrokerPositionSnapshot,
    U19ExecutionEvent,
    U19ExecutionLedgerSnapshot,
    U19Position,
    U19RecoveryStatus,
)
from environments.virtual.position.track2_u19_recovery_store import SqliteTrack2U19RecoveryStore


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



def test_duplicate_execution_does_not_overwrite_applied_provenance_metadata():
    bridge = _bridge()
    plan, leg, identity, command, report = _inputs()
    bridge._apply_reconciled_execution(
        plan=plan, leg=leg, identity=identity,
        broker_command=command, report=report,
    )
    before_provenance = dict(bridge.provenance["S8-FILL-001"])
    before_execution_leg = dict(bridge.execution_legs["S8-FILL-001"])

    replay_plan = replace(plan, strategy_id="SYNTHETIC_REPLAY_STRATEGY")
    replay_leg = SimpleNamespace(
        leg_id=leg.leg_id, side=leg.side,
        position_role=PositionRole.EVENT_INSURANCE.value,
    )
    bridge._apply_reconciled_execution(
        plan=replay_plan, leg=replay_leg, identity=identity,
        broker_command=command, report=report,
    )

    assert bridge.provenance["S8-FILL-001"] == before_provenance
    assert bridge.execution_legs["S8-FILL-001"] == before_execution_leg
    assert len(bridge.position_lot_store.history()) == 2
    assert len(bridge.fee_ledger.query(run_id=bridge.run_id)) == 2
    assert bridge.leg_positions[identity.instrument_id].qty == 3


def test_conflicting_execution_does_not_overwrite_applied_provenance_metadata():
    bridge = _bridge()
    plan, leg, identity, command, report = _inputs()
    bridge._apply_reconciled_execution(
        plan=plan, leg=leg, identity=identity,
        broker_command=command, report=report,
    )
    before_provenance = dict(bridge.provenance["S8-FILL-001"])
    before_execution_leg = dict(bridge.execution_legs["S8-FILL-001"])
    before_fingerprint = bridge._applied_execution_fingerprints["S8-FILL-001"]

    conflicting_fill = ExecutionFill(
        "S8-FILL-001", 1, Decimal("10.25"),
        report.execution_fills[0].execution_timestamp, Decimal("0.10"),
    )
    conflicting_report = replace(
        report, execution_fills=(conflicting_fill, report.execution_fills[1]),
    )
    conflicting_plan = replace(plan, strategy_id="SYNTHETIC_CONFLICT_STRATEGY")
    conflicting_leg = SimpleNamespace(
        leg_id=leg.leg_id, side=leg.side,
        position_role=PositionRole.EVENT_INSURANCE.value,
    )

    with pytest.raises(
        RuntimeError,
        match="MULTI_LEG_EXECUTION_ID_CONFLICT_RECONCILIATION_REQUIRED",
    ):
        bridge._apply_reconciled_execution(
            plan=conflicting_plan, leg=conflicting_leg, identity=identity,
            broker_command=command, report=conflicting_report,
        )

    assert bridge.provenance["S8-FILL-001"] == before_provenance
    assert bridge.execution_legs["S8-FILL-001"] == before_execution_leg
    assert bridge._applied_execution_fingerprints["S8-FILL-001"] == before_fingerprint
    assert len(bridge.position_lot_store.history()) == 2
    assert len(bridge.fee_ledger.query(run_id=bridge.run_id)) == 2
    assert bridge.fee_ledger.total(run_id=bridge.run_id) == Decimal("0.30")
    assert bridge.leg_positions[identity.instrument_id].qty == 3



def test_partial_fill_order_execution_position_lots_reconcile_through_u19_checkpoint(tmp_path):
    bridge = _bridge()
    plan, leg, identity, command, report = _inputs()
    bridge._apply_reconciled_execution(
        plan=plan, leg=leg, identity=identity,
        broker_command=command, report=report,
    )

    lots = bridge.position_lot_store.history()
    assert len(lots) == 2
    assert [lot.opened_quantity for lot in lots] == [1, 2]
    assert {lot.client_order_id for lot in lots} == {command.client_order_id}
    assert {lot.group_id for lot in lots} == {plan.group_id}
    assert {lot.leg_id for lot in lots} == {leg.leg_id}
    assert {lot.instrument_id for lot in lots} == {identity.instrument_id}

    def digest(value):
        body = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    lot_by_execution = {lot.execution_id: lot for lot in lots}
    assert len(lot_by_execution) == 2
    execution_events = tuple(
        U19ExecutionEvent(
            lot.execution_id,
            digest({
                "client_order_id": lot.client_order_id,
                "group_id": lot.group_id,
                "leg_id": lot.leg_id,
                "instrument_id": lot.instrument_id,
                "side": lot.side,
                "opened_quantity": lot.opened_quantity,
                "execution_timestamp": lot.execution_timestamp,
            }),
        )
        for lot in lots
    )
    assert {event.execution_id for event in execution_events} == set(lot_by_execution)

    aggregate_quantity = sum(
        lot.opened_quantity if lot.side == "BUY" else -lot.opened_quantity
        for lot in lots
    )
    positions = (U19Position(identity.instrument_id, Decimal(str(aggregate_quantity))),)
    as_of = datetime(2026, 11, 3, 0, 0, tzinfo=timezone.utc)
    broker_payload = {
        "group_id": plan.group_id,
        "positions": [(item.instrument_id, str(item.signed_quantity)) for item in positions],
    }
    ledger_payload = {
        **broker_payload,
        "execution_events": [
            (event.execution_id, event.fingerprint) for event in execution_events
        ],
    }
    broker_snapshot = U19BrokerPositionSnapshot(
        group_id=plan.group_id,
        snapshot_id="validation-partial-fill-broker",
        as_of=as_of,
        source="VALIDATION_ONLY:BROKER_EXCHANGE",
        positions=positions,
        complete=True,
        capability_verified=True,
        payload_sha256=digest(broker_payload),
    )
    ledger_snapshot = U19ExecutionLedgerSnapshot(
        group_id=plan.group_id,
        snapshot_id="validation-partial-fill-ledger",
        as_of=as_of,
        source="VALIDATION_ONLY:EXECUTION_LEDGER",
        positions=positions,
        complete=True,
        payload_sha256=digest(ledger_payload),
        execution_events=execution_events,
        pending_order_ids=(),
    )

    checkpoint_path = tmp_path / "partial-fill-u19.sqlite3"
    decision = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(checkpoint_path)
    ).recover(
        group_id=plan.group_id,
        broker_snapshot=broker_snapshot,
        ledger_snapshot=ledger_snapshot,
    )
    assert decision.status is U19RecoveryStatus.RESTORE_ALLOWED
    assert decision.positions == positions
    assert decision.execution_events == execution_events
    assert decision.new_entry_enabled is False
    assert decision.order_submission_enabled is False

    persisted = SqliteTrack2U19RecoveryStore(checkpoint_path).load_latest(plan.group_id)
    assert persisted["status"] == U19RecoveryStatus.RESTORE_ALLOWED.value
    assert persisted["positions"] == [
        {"instrument_id": identity.instrument_id, "signed_quantity": "3"}
    ]
    assert {item["execution_id"] for item in persisted["execution_events"]} == set(lot_by_execution)
    assert persisted["pending_order_ids"] == []


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "group_id",
            "SYNTHETIC:WRONG-GROUP",
            "MULTI_LEG_EXECUTION_GROUP_LINEAGE_MISMATCH",
        ),
        (
            "leg_id",
            "SYNTHETIC:WRONG-LEG",
            "MULTI_LEG_EXECUTION_LEG_LINEAGE_MISMATCH",
        ),
        (
            "client_order_id",
            "SYNTHETIC:WRONG-ORDER",
            "MULTI_LEG_EXECUTION_ORDER_LINEAGE_MISMATCH",
        ),
    ],
)
def test_execution_lineage_mismatch_fails_closed_before_any_position_or_fee_mutation(
    field, value, message
):
    bridge = _bridge()
    plan, leg, identity, command, report = _inputs()
    conflicting = replace(report, **{field: value})

    with pytest.raises(RuntimeError, match=message):
        bridge._apply_reconciled_execution(
            plan=plan,
            leg=leg,
            identity=identity,
            broker_command=command,
            report=conflicting,
        )

    assert bridge.position_lot_store.history() == ()
    assert bridge.leg_positions == {}
    assert bridge.execution_legs == {}
    assert bridge.provenance == {}
    assert bridge.fee_ledger.query(run_id=bridge.run_id) == ()

def test_legacy_execution_report_without_group_leg_uses_active_plan_lineage():
    bridge = _bridge()
    plan, leg, identity, command, report = _inputs()
    legacy_report = replace(report, group_id=None, leg_id=None)

    bridge._apply_reconciled_execution(
        plan=plan,
        leg=leg,
        identity=identity,
        broker_command=command,
        report=legacy_report,
    )

    lots = bridge.position_lot_store.history()
    assert len(lots) == 2
    assert all(lot.group_id == plan.group_id for lot in lots)
    assert all(lot.leg_id == leg.leg_id for lot in lots)
    assert all(lot.client_order_id == command.client_order_id for lot in lots)


def test_multi_fill_expansion_preserves_outer_group_leg_order_lineage():
    report = ExecutionReport(
        client_order_id="SYNTHETIC:MULTI-FILL-ORDER",
        broker_order_id="SYNTHETIC:MULTI-FILL-BROKER",
        execution_id=None,
        status="PARTIALLY_FILLED",
        filled_quantity=3,
        remaining_quantity=1,
        execution_price=Decimal("10.5"),
        execution_timestamp=datetime(2026, 11, 19, 9, 30),
        fee=Decimal("0.2"),
        group_id="SYNTHETIC:MULTI-FILL-GROUP",
        leg_id="SYNTHETIC:MULTI-FILL-LEG",
        execution_fills=(
            ExecutionFill(
                execution_id="SYNTHETIC:FILL-1",
                filled_quantity=1,
                execution_price=Decimal("10.0"),
                execution_timestamp=datetime(2026, 11, 19, 9, 30),
                fee=Decimal("0.1"),
            ),
            ExecutionFill(
                execution_id="SYNTHETIC:FILL-2",
                filled_quantity=2,
                execution_price=Decimal("10.75"),
                execution_timestamp=datetime(2026, 11, 19, 9, 30, 1),
                fee=Decimal("0.1"),
            ),
        ),
    )

    expanded = VirtualMultiLegExecutionBridge._execution_fill_reports(report)

    assert len(expanded) == 2
    assert sum(item.filled_quantity for item in expanded) == report.filled_quantity
    assert all(item.group_id == report.group_id for item in expanded)
    assert all(item.leg_id == report.leg_id for item in expanded)
    assert all(item.client_order_id == report.client_order_id for item in expanded)

@pytest.mark.parametrize(
    ("fill_mutation", "expected_error"),
    [
        (
            lambda report: (
                report.execution_fills[0],
                replace(report.execution_fills[1], execution_id=report.execution_fills[0].execution_id),
            ),
            "MULTI_LEG_EXECUTION_FILL_ID_DUPLICATE",
        ),
        (
            lambda report: (
                report.execution_fills[0],
                replace(report.execution_fills[1], filled_quantity=1),
            ),
            "MULTI_LEG_EXECUTION_FILL_TOTAL_MISMATCH",
        ),
    ],
)
def test_invalid_multi_fill_expansion_is_rejected_before_position_or_fee_mutation(
    fill_mutation, expected_error,
):
    bridge = _bridge()
    plan, leg, identity, command, report = _inputs()
    conflicting = replace(report, execution_fills=fill_mutation(report))

    with pytest.raises(RuntimeError, match=expected_error):
        bridge._apply_reconciled_execution(
            plan=plan, leg=leg, identity=identity,
            broker_command=command, report=conflicting,
        )

    assert bridge.position_lot_store.history() == ()
    assert bridge.leg_positions == {}
    assert bridge.execution_legs == {}
    assert bridge.provenance == {}
    assert bridge.fee_ledger.query(run_id=bridge.run_id) == ()


def test_legacy_aggregate_only_execution_report_keeps_single_event_compatibility():
    _, _, _, _, report = _inputs()
    aggregate_only = replace(
        report,
        execution_id="S8-LEGACY-AGGREGATE-FILL",
        execution_fills=(),
    )

    expanded = VirtualMultiLegExecutionBridge._execution_fill_reports(aggregate_only)

    assert expanded == (aggregate_only,)
    assert expanded[0].execution_id == "S8-LEGACY-AGGREGATE-FILL"
    assert expanded[0].filled_quantity == aggregate_only.filled_quantity


def test_multi_fill_conflict_is_preflighted_before_any_new_fill_mutation():
    bridge = _bridge()
    plan, leg, identity, command, report = _inputs()
    second_fill = replace(report.execution_fills[1], execution_price=Decimal("11.50"))
    previously_applied = replace(
        report,
        execution_id=None,
        filled_quantity=second_fill.filled_quantity,
        remaining_quantity=3,
        execution_price=second_fill.execution_price,
        execution_timestamp=second_fill.execution_timestamp,
        fee=second_fill.fee,
        execution_fills=(second_fill,),
    )
    bridge._apply_reconciled_execution(
        plan=plan, leg=leg, identity=identity,
        broker_command=command, report=previously_applied,
    )
    before_lots = bridge.position_lot_store.history()
    before_fees = bridge.fee_ledger.query(run_id=bridge.run_id)
    before_position = bridge.leg_positions[identity.instrument_id].qty
    before_leg_positions = dict(bridge.leg_positions)
    before_fingerprints = dict(bridge._applied_execution_fingerprints)
    before_execution_legs = dict(bridge.execution_legs)
    before_provenance = dict(bridge.provenance)

    conflicting_fill = replace(second_fill, execution_price=Decimal("11.00"))
    conflicting = replace(
        report,
        execution_fills=(report.execution_fills[0], conflicting_fill),
    )
    with pytest.raises(
        RuntimeError,
        match="MULTI_LEG_EXECUTION_ID_CONFLICT_RECONCILIATION_REQUIRED",
    ):
        bridge._apply_reconciled_execution(
            plan=plan, leg=leg, identity=identity,
            broker_command=command, report=conflicting,
        )

    assert bridge.position_lot_store.history() == before_lots
    assert bridge.fee_ledger.query(run_id=bridge.run_id) == before_fees
    assert bridge.leg_positions[identity.instrument_id].qty == before_position
    assert bridge.leg_positions == before_leg_positions
    assert bridge._applied_execution_fingerprints == before_fingerprints
    assert bridge.execution_legs == before_execution_legs
    assert bridge.provenance == before_provenance

    corrected = replace(
        report,
        execution_fills=(report.execution_fills[0], second_fill),
    )
    bridge._apply_reconciled_execution(
        plan=plan, leg=leg, identity=identity,
        broker_command=command, report=corrected,
    )
    assert [(lot.execution_id, lot.opened_quantity) for lot in bridge.position_lot_store.history()] == [
        ("S8-FILL-002", 2),
        ("S8-FILL-001", 1),
    ]
    assert bridge.leg_positions[identity.instrument_id].qty == 3
    assert bridge.fee_ledger.total(run_id=bridge.run_id) == Decimal("0.30")



@pytest.mark.parametrize("fault_stage", ["position_lot", "fee_ledger", "position_aggregate"])
def test_bridge_mutation_failure_can_replay_without_cross_ledger_double_count(
    monkeypatch, fault_stage,
):
    bridge = _bridge()
    plan, leg, identity, command, report = _inputs()
    from environments.virtual.position.virtual_position_aggregate import VirtualPositionAggregate

    targets = {
        "position_lot": (type(bridge.position_lot_store), "apply_execution"),
        "fee_ledger": (type(bridge.fee_ledger), "record"),
        "position_aggregate": (VirtualPositionAggregate, "apply_fill"),
    }
    target_class, method_name = targets[fault_stage]
    original_apply = getattr(target_class, method_name)
    injected = {"raised": False}

    def apply_then_raise_once(self, *args, **kwargs):
        original_apply(self, *args, **kwargs)
        if not injected["raised"]:
            injected["raised"] = True
            raise RuntimeError(f"SYNTHETIC_FAULT_AFTER_{fault_stage.upper()}_MUTATION")

    monkeypatch.setattr(target_class, method_name, apply_then_raise_once)
    with pytest.raises(RuntimeError, match=f"SYNTHETIC_FAULT_AFTER_{fault_stage.upper()}_MUTATION"):
        bridge._apply_reconciled_execution(
            plan=plan, leg=leg, identity=identity,
            broker_command=command, report=report,
        )

    assert len(bridge.position_lot_store.history()) == 1
    expected_fee_rows = 1 if fault_stage in {"fee_ledger", "position_aggregate"} else 0
    assert len(bridge.fee_ledger.query(run_id=bridge.run_id)) == expected_fee_rows
    assert bridge.leg_positions == {}
    assert bridge._applied_execution_fingerprints == {}
    assert bridge.execution_legs == {}
    assert bridge.provenance == {}

    monkeypatch.setattr(target_class, method_name, original_apply)
    bridge._apply_reconciled_execution(
        plan=plan, leg=leg, identity=identity,
        broker_command=command, report=report,
    )

    assert len(bridge.position_lot_store.history()) == 2
    assert len(bridge.fee_ledger.query(run_id=bridge.run_id)) == 2
    assert bridge.fee_ledger.total(run_id=bridge.run_id) == Decimal("0.30")
    assert bridge.leg_positions[identity.instrument_id].qty == 3
    assert len(bridge._applied_execution_fingerprints) == 2


@pytest.mark.parametrize("fault_mapping", ["leg_positions", "_applied_execution_fingerprints", "execution_legs", "provenance"])
def test_bridge_publish_mapping_failure_rolls_back_indexes_and_replays_cleanly(fault_mapping):
    bridge = _bridge()
    plan, leg, identity, command, report = _inputs()

    class FailAfterSetDict(dict):
        def __init__(self):
            super().__init__()
            self.armed = True

        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            if self.armed:
                self.armed = False
                raise RuntimeError(f"SYNTHETIC_FAULT_AFTER_{fault_mapping.upper()}_PUBLISH")

    setattr(bridge, fault_mapping, FailAfterSetDict())
    with pytest.raises(RuntimeError, match=f"SYNTHETIC_FAULT_AFTER_{fault_mapping.upper()}_PUBLISH"):
        bridge._apply_reconciled_execution(
            plan=plan, leg=leg, identity=identity,
            broker_command=command, report=report,
        )

    assert len(bridge.position_lot_store.history()) == 1
    assert len(bridge.fee_ledger.query(run_id=bridge.run_id)) == 1
    assert bridge.leg_positions == {}
    assert bridge._applied_execution_fingerprints == {}
    assert bridge.execution_legs == {}
    assert bridge.provenance == {}

    for mapping_name in ("leg_positions", "_applied_execution_fingerprints", "execution_legs", "provenance"):
        setattr(bridge, mapping_name, dict(getattr(bridge, mapping_name)))
    bridge._apply_reconciled_execution(
        plan=plan, leg=leg, identity=identity,
        broker_command=command, report=report,
    )

    assert len(bridge.position_lot_store.history()) == 2
    assert len(bridge.fee_ledger.query(run_id=bridge.run_id)) == 2
    assert bridge.fee_ledger.total(run_id=bridge.run_id) == Decimal("0.30")
    assert bridge.leg_positions[identity.instrument_id].qty == 3
    assert len(bridge._applied_execution_fingerprints) == 2
    assert len(bridge.execution_legs) == 2
    assert len(bridge.provenance) == 2


@pytest.mark.parametrize("fault_mapping", ["leg_positions", "_applied_execution_fingerprints", "execution_legs", "provenance"])
def test_second_fill_publication_failure_preserves_first_fill_and_replays_only_second(fault_mapping):
    bridge = _bridge()
    plan, leg, identity, command, report = _inputs()

    class FailAfterSecondSetDict(dict):
        def __init__(self):
            super().__init__()
            self.set_count = 0

        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            self.set_count += 1
            if self.set_count == 2:
                raise RuntimeError(f"SYNTHETIC_FAULT_AFTER_SECOND_FILL_{fault_mapping.upper()}_PUBLISH")

    setattr(bridge, fault_mapping, FailAfterSecondSetDict())
    with pytest.raises(RuntimeError, match=f"SYNTHETIC_FAULT_AFTER_SECOND_FILL_{fault_mapping.upper()}_PUBLISH"):
        bridge._apply_reconciled_execution(
            plan=plan, leg=leg, identity=identity,
            broker_command=command, report=report,
        )

    assert len(bridge.position_lot_store.history()) == 2
    assert len(bridge.fee_ledger.query(run_id=bridge.run_id)) == 2
    assert bridge.fee_ledger.total(run_id=bridge.run_id) == Decimal("0.30")
    assert bridge.leg_positions[identity.instrument_id].qty == 1
    assert set(bridge._applied_execution_fingerprints) == {"S8-FILL-001"}
    assert set(bridge.execution_legs) == {"S8-FILL-001"}
    assert set(bridge.provenance) == {"S8-FILL-001"}

    for mapping_name in ("leg_positions", "_applied_execution_fingerprints", "execution_legs", "provenance"):
        setattr(bridge, mapping_name, dict(getattr(bridge, mapping_name)))
    bridge._apply_reconciled_execution(
        plan=plan, leg=leg, identity=identity,
        broker_command=command, report=report,
    )

    assert len(bridge.position_lot_store.history()) == 2
    assert len(bridge.fee_ledger.query(run_id=bridge.run_id)) == 2
    assert bridge.fee_ledger.total(run_id=bridge.run_id) == Decimal("0.30")
    assert bridge.leg_positions[identity.instrument_id].qty == 3
    assert set(bridge._applied_execution_fingerprints) == {"S8-FILL-001", "S8-FILL-002"}
    assert set(bridge.execution_legs) == {"S8-FILL-001", "S8-FILL-002"}
    assert set(bridge.provenance) == {"S8-FILL-001", "S8-FILL-002"}
