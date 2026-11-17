from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from application.composition.validation_only_account_snapshot_assembler import (
    AccountSnapshotBundle,
    SnapshotSection,
    SyntheticSnapshotProvenance,
    snapshot_rows_sha256,
    validate_account_snapshot_bundle,
)
from application.composition.validation_only_account_snapshot_u19_reconciler import (
    ValidationOnlyAccountSnapshotU19Reconciler,
)
from application.composition.track2_u19_ledger_snapshot_builder import (
    ValidationOnlyU19LedgerSnapshotBuilder,
)
from application.composition.track2_u19_recovery import ValidationOnlyTrack2U19RecoveryCoordinator
from contracts.types import BrokerOrderCommand, ExecutionReport, OrderAckEvent, OrderIntent
from core.oms.oms_fsm import OrderStateMachine
from core.oms.track2_u19_recovery import U19RecoveryStatus
from environments.live.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.live.position.live_execution_position_bridge import (
    LiveExecutionPositionBridge,
    LivePositionFillAdapter,
)
from environments.live.position.live_position_aggregate import LivePositionAggregate
from environments.live.settlement.sqlite_settlement_store import SQLiteSettlementStore
from environments.virtual.position.track2_u19_recovery_store import SqliteTrack2U19RecoveryStore


AS_OF = datetime(2026, 11, 18, 10, 0, tzinfo=timezone.utc)
GROUP_ID = "SYNTHETIC:GROUP:ACCOUNT-U19"


def _section(snapshot_id, as_of, rows):
    return SnapshotSection(
        snapshot_id=snapshot_id,
        as_of=as_of,
        source="VALIDATION_ONLY:SYNTHETIC_ACCOUNT_FIXTURE",
        payload_sha256=snapshot_rows_sha256(rows),
        rows=tuple(rows),
    )


def _bundle(*, final_quantity=4, executions=None):
    instrument = "SYNTHETIC_CONTRACT:KOSPI200_CALL_202612"
    orders = (
        {
            "client_order_id": "client-old", "broker_order_id": "broker-old",
            "instrument_id": instrument, "side": "BUY", "order_quantity": 3,
            "cumulative_filled_quantity": 2, "status": "CANCELLED",
        },
        {
            "client_order_id": "client-replacement", "broker_order_id": "broker-replacement",
            "instrument_id": instrument, "side": "BUY", "order_quantity": 2,
            "cumulative_filled_quantity": 1, "status": "PARTIALLY_FILLED",
            "replaces_broker_order_id": "broker-old",
        },
    )
    fills = executions or (
        {
            "execution_id": "SYNTHETIC:FILL-001", "client_order_id": "client-old",
            "broker_order_id": "broker-old", "instrument_id": instrument,
            "side": "BUY", "filled_quantity": 1, "execution_price": "10.00",
            "execution_timestamp": AS_OF - timedelta(minutes=5),
        },
        {
            "execution_id": "SYNTHETIC:FILL-002", "client_order_id": "client-old",
            "broker_order_id": "broker-old", "instrument_id": instrument,
            "side": "BUY", "filled_quantity": 1, "execution_price": "10.10",
            "execution_timestamp": AS_OF - timedelta(minutes=4),
        },
        {
            "execution_id": "SYNTHETIC:FILL-003", "client_order_id": "client-replacement",
            "broker_order_id": "broker-replacement", "instrument_id": instrument,
            "side": "BUY", "filled_quantity": 1, "execution_price": "10.20",
            "execution_timestamp": AS_OF - timedelta(minutes=2),
        },
    )
    opening_as_of = AS_OF - timedelta(minutes=10)
    opening = ({
        "instrument_id": instrument, "side": "LONG", "quantity": 1, "avg_price": "9.75",
    },)
    positions = ({
        "instrument_id": instrument, "side": "LONG", "quantity": final_quantity,
        "avg_price": "10.10",
    },)
    return AccountSnapshotBundle(
        orders=_section("orders-account", AS_OF, orders),
        executions=_section("executions-account", AS_OF, fills),
        positions=_section("positions-account", AS_OF, positions),
        opening_positions=_section("opening-account", opening_as_of, opening),
        provenance=SyntheticSnapshotProvenance(
            namespace="SYNTHETIC:DERIVED_SCENARIO",
            deterministic_rule_id="account-u19-four-way-v1",
            manifest_sha256="b" * 64,
            scenario_timestamp=AS_OF,
            source_anchor_refs=("TEST_ONLY:account-opening-anchor",),
            source_anchor_as_of=opening_as_of,
        ),
    )


def _seed_order(
    store, *, client_id, broker_id, instrument, quantity, leg_id, fills,
):
    oms = OrderStateMachine(persistence_store=store)
    oms.apply_intent(OrderIntent(
        client_order_id=client_id, instrument_id=instrument, side="BUY",
        quantity=quantity, intent_type="OPEN", strategy_id="S2",
        group_id=GROUP_ID, leg_id=leg_id,
    ))
    oms.register_broker_order_command(BrokerOrderCommand(
        client_order_id=client_id, instrument_id=instrument, side="BUY",
        quantity=quantity, order_type="LIMIT", broker_symbol=instrument,
        asset_type="OPTION", strategy_id="S2", group_id=GROUP_ID,
        leg_id=leg_id, position_role="OPEN",
    ))
    oms.apply_ack(OrderAckEvent(client_order_id=client_id, accepted=True, broker_order_id=broker_id))
    position = LivePositionAggregate(instrument)
    bridge = LiveExecutionPositionBridge(
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(position),
        execution_event_deduplicator=ExecutionEventDeduplicator(persistence_store=store),
        position_aggregate=position,
        settlement_store=store,
    )
    for index, (execution_id, quantity_filled, price) in enumerate(fills):
        cumulative = sum(item[1] for item in fills[: index + 1])
        bridge.settle(ExecutionReport(
            client_order_id=client_id, broker_order_id=broker_id,
            execution_id=execution_id,
            status="FILLED" if cumulative == quantity else "PARTIALLY_FILLED",
            filled_quantity=quantity_filled, remaining_quantity=quantity - cumulative,
            execution_price=Decimal(price),
            execution_timestamp=AS_OF - timedelta(minutes={"SYNTHETIC:FILL-001": 5, "SYNTHETIC:FILL-002": 4, "SYNTHETIC:FILL-003": 2}[execution_id]),
            fee=Decimal("1"), group_id=GROUP_ID, leg_id=leg_id,
        ))
    return oms


def _make_reconciler(tmp_path, *, old_first_fill_quantity=1):
    instrument = "SYNTHETIC_CONTRACT:KOSPI200_CALL_202612"
    settlement = SQLiteSettlementStore(tmp_path / "settlement.sqlite3")
    old = _seed_order(
        settlement, client_id="client-old", broker_id="broker-old",
        instrument=instrument, quantity=(3 if old_first_fill_quantity == 1 else 4), leg_id="call",
        fills=(('SYNTHETIC:FILL-001', old_first_fill_quantity, '10.00'), ('SYNTHETIC:FILL-002', 1, '10.10')),
    )
    old.apply_cancel(ExecutionReport(
        client_order_id="client-old", broker_order_id="broker-old",
        execution_id="SYNTHETIC:CANCEL-ACK", status="CANCELLED",
        filled_quantity=0, remaining_quantity=1, execution_price=None,
        execution_timestamp=AS_OF - timedelta(minutes=1),
        group_id=GROUP_ID, leg_id="call",
    ))
    _seed_order(
        settlement, client_id="client-replacement", broker_id="broker-replacement",
        instrument=instrument, quantity=2, leg_id="call",
        fills=(("SYNTHETIC:FILL-003", 1, "10.20"),),
    )
    settlement.record_order_replacement_link(
        link_id="SYNTHETIC:REPLACE-001",
        original_client_order_id="client-old", original_broker_order_id="broker-old",
        replacement_client_order_id="client-replacement",
        replacement_broker_order_id="broker-replacement",
        group_id=GROUP_ID, leg_id="call",
        cancel_request_ref="VALIDATION_ONLY:CANCEL-REQUEST",
        cancel_ack_ref="VALIDATION_ONLY:CANCEL-ACK",
        source="VALIDATION_ONLY:ORDER_REPLACEMENT_FIXTURE", payload={},
    )
    checkpoint = SqliteTrack2U19RecoveryStore(tmp_path / "u19-checkpoint.sqlite3")
    coordinator = ValidationOnlyTrack2U19RecoveryCoordinator(
        checkpoint, settlement_store=settlement,
    )
    reconciler = ValidationOnlyAccountSnapshotU19Reconciler(
        ledger_snapshot_builder=ValidationOnlyU19LedgerSnapshotBuilder(settlement),
        recovery_coordinator=coordinator,
    )
    return reconciler, checkpoint.path


def test_account_snapshot_bundle_reconciles_four_ways_through_u19_and_checkpoint_reopen(tmp_path):
    bundle = _bundle()
    validation = validate_account_snapshot_bundle(bundle)
    assert validation.is_valid
    reconciler, checkpoint_path = _make_reconciler(tmp_path)

    result = reconciler.reconcile(
        bundle=bundle, validation=validation, group_id=GROUP_ID,
        snapshot_id="account-four-way-001", as_of=AS_OF,
    )

    assert result.is_valid
    assert result.issues == ()
    assert result.ledger_snapshot is not None
    assert {event.execution_id for event in result.ledger_snapshot.execution_events} == {
        "SYNTHETIC:FILL-001", "SYNTHETIC:FILL-002", "SYNTHETIC:FILL-003",
    }
    assert result.projected_ledger_snapshot.positions == result.broker_snapshot.positions
    assert result.recovery_decision.status is U19RecoveryStatus.RESTORE_ALLOWED
    assert result.recovery_decision.new_entry_enabled is False
    assert result.recovery_decision.order_submission_enabled is False

    reopened = SqliteTrack2U19RecoveryStore(checkpoint_path)
    checkpoint = reopened.load_latest(GROUP_ID)
    assert checkpoint["status"] == U19RecoveryStatus.RESTORE_ALLOWED.value
    assert checkpoint["broker_positions"] == checkpoint["ledger_positions"]
    assert {item["execution_id"] for item in checkpoint["execution_events"]} == {
        "SYNTHETIC:FILL-001", "SYNTHETIC:FILL-002", "SYNTHETIC:FILL-003",
    }
    assert checkpoint["new_entry_enabled"] is False
    assert checkpoint["order_submission_enabled"] is False


def test_account_snapshot_u19_mismatch_is_reconciliation_required_not_immediate_block(tmp_path):
    bundle = _bundle()
    validation = validate_account_snapshot_bundle(bundle)
    assert validation.is_valid
    reconciler, _ = _make_reconciler(tmp_path, old_first_fill_quantity=2)

    result = reconciler.reconcile(
        bundle=bundle, validation=validation, group_id=GROUP_ID,
        snapshot_id="account-position-mismatch", as_of=AS_OF,
    )

    assert result.status == "RECONCILIATION_REQUIRED"
    assert "ACCOUNT_POSITION_U19_LEDGER_PROJECTION_MISMATCH" in result.issues
    assert "ACCOUNT_U19_EXECUTION_QUANTITY_MISMATCH:SYNTHETIC:FILL-001" in result.issues
    assert result.recovery_decision.status is U19RecoveryStatus.POSITION_LEDGER_MISMATCH


def test_account_snapshot_u19_execution_id_gap_requests_reconciliation(tmp_path):
    bundle = _bundle()
    changed = tuple(
        {**row, "execution_id": "SYNTHETIC:FILL-UNKNOWN"}
        if row["execution_id"] == "SYNTHETIC:FILL-003" else row
        for row in bundle.executions.rows
    )
    bundle = replace(bundle, executions=_section(bundle.executions.snapshot_id, AS_OF, changed))
    validation = validate_account_snapshot_bundle(bundle)
    assert validation.is_valid
    reconciler, _ = _make_reconciler(tmp_path)

    result = reconciler.reconcile(
        bundle=bundle, validation=validation, group_id=GROUP_ID,
        snapshot_id="account-execution-gap", as_of=AS_OF,
    )

    assert result.status == "RECONCILIATION_REQUIRED"
    assert "ACCOUNT_U19_EXECUTION_ID_SET_MISMATCH" in result.issues
    assert result.recovery_decision is None


def test_account_snapshot_u19_preserves_pending_late_fill_gate(tmp_path):
    reconciler, _ = _make_reconciler(tmp_path)
    settlement = reconciler.ledger_snapshot_builder.settlement_store
    settlement.record_late_fill_pending(
        execution_id="SYNTHETIC:LATE-FILL-PENDING",
        client_order_id="client-old", broker_order_id="broker-old",
        payload={"execution_id": "SYNTHETIC:LATE-FILL-PENDING", "source": "VALIDATION_ONLY"},
    )
    bundle = _bundle()
    validation = validate_account_snapshot_bundle(bundle)

    result = reconciler.reconcile(
        bundle=bundle, validation=validation, group_id=GROUP_ID,
        snapshot_id="account-pending-late-fill", as_of=AS_OF,
    )

    assert result.status == "RECONCILIATION_REQUIRED"
    assert result.recovery_decision.status is U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED
    assert result.recovery_decision.new_entry_enabled is False
    assert result.recovery_decision.order_submission_enabled is False


def test_account_snapshot_missing_section_or_invalid_validation_does_not_call_u19_builder(tmp_path):
    bundle = _bundle()
    invalid = replace(
        validate_account_snapshot_bundle(bundle),
        status="RECONCILIATION_REQUIRED",
        issues=("SNAPSHOT_SECTION_MISSING:EXECUTIONS",),
    )
    reconciler, _ = _make_reconciler(tmp_path)

    result = reconciler.reconcile(
        bundle=bundle, validation=invalid, group_id=GROUP_ID,
        snapshot_id="account-missing-section", as_of=AS_OF,
    )

    assert result.status == "RECONCILIATION_REQUIRED"
    assert result.issues == ("SNAPSHOT_SECTION_MISSING:EXECUTIONS",)
    assert result.ledger_snapshot is None







def test_account_snapshot_u19_as_of_mismatch_is_reconciliation_required(tmp_path):
    bundle = _bundle()
    validation = validate_account_snapshot_bundle(bundle)
    reconciler, _ = _make_reconciler(tmp_path)

    result = reconciler.reconcile(
        bundle=bundle, validation=validation, group_id=GROUP_ID,
        snapshot_id="account-as-of-mismatch", as_of=AS_OF + timedelta(minutes=1),
    )

    assert result.status == "RECONCILIATION_REQUIRED"
    assert "ACCOUNT_U19_SNAPSHOT_AS_OF_MISMATCH" in result.issues
    assert result.recovery_decision.status is U19RecoveryStatus.SNAPSHOT_AS_OF_MISMATCH
