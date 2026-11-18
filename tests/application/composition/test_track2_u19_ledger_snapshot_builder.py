from datetime import datetime, timezone
from decimal import Decimal
import sqlite3

import pytest

from application.composition.track2_u19_ledger_snapshot_builder import (
    U19LedgerSnapshotBuildError,
    ValidationOnlyU19LedgerSnapshotBuilder,
)
from application.composition.track2_u19_recovery import ValidationOnlyTrack2U19RecoveryCoordinator
from contracts.types import BrokerOrderCommand, ExecutionReport, OrderAckEvent, OrderIntent
from core.oms.oms_fsm import OrderStateMachine, OrderStateTransitionError
from core.oms.track2_u19_recovery import (
    U19BrokerPositionSnapshot,
    U19Position,
    U19RecoveryStatus,
)
from environments.live.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.live.position.live_execution_position_bridge import (
    LiveExecutionPositionBridge,
    LivePositionFillAdapter,
)
from environments.live.position.live_position_aggregate import LivePositionAggregate
from environments.live.settlement.sqlite_settlement_store import SQLiteSettlementStore, SettlementStoreError
from environments.virtual.position.track2_u19_recovery_store import SqliteTrack2U19RecoveryStore


AS_OF = datetime(2026, 11, 18, 10, 0, tzinfo=timezone.utc)
GROUP_ID = "SYNTHETIC:GROUP:U19-LEDGER"


def _order_with_fill(store, *, client_id, broker_id, instrument_id, side, leg_id, group_id=GROUP_ID,
                     fills=(("exec-1", 1, 0, "10.00"),), order_quantity=None, position_aggregate=None):
    oms = OrderStateMachine(persistence_store=store)
    quantity = order_quantity if order_quantity is not None else sum(item[1] for item in fills)
    oms.apply_intent(OrderIntent(
        client_order_id=client_id,
        instrument_id=instrument_id,
        side=side,
        quantity=quantity,
        intent_type="OPEN",
        strategy_id="S2",
        group_id=group_id,
        leg_id=leg_id,
    ))
    command = BrokerOrderCommand(
        client_order_id=client_id,
        instrument_id=instrument_id,
        side=side,
        quantity=quantity,
        order_type="LIMIT",
        broker_symbol=instrument_id,
        asset_type="OPTION",
        strategy_id="S2",
        group_id=group_id,
        leg_id=leg_id,
        position_role="OPEN",
    )
    oms.register_broker_order_command(command)
    oms.apply_ack(OrderAckEvent(client_order_id=client_id, accepted=True, broker_order_id=broker_id))
    position = position_aggregate or LivePositionAggregate(instrument_id)
    if position.instrument_id != instrument_id:
        raise ValueError("TEST_POSITION_AGGREGATE_INSTRUMENT_MISMATCH")
    bridge = LiveExecutionPositionBridge(
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(position),
        execution_event_deduplicator=ExecutionEventDeduplicator(persistence_store=store),
        position_aggregate=position,
        settlement_store=store,
    )
    cumulative = 0
    for index, (execution_id, fill_qty, _unused, price) in enumerate(fills):
        cumulative += fill_qty
        status = "FILLED" if cumulative == quantity else "PARTIALLY_FILLED"
        report = ExecutionReport(
            client_order_id=client_id,
            broker_order_id=broker_id,
            execution_id=execution_id,
            status=status,
            filled_quantity=fill_qty,
            remaining_quantity=quantity - cumulative,
            execution_price=Decimal(price),
            execution_timestamp=datetime(2026, 11, 18, 9, 30 + index, tzinfo=timezone.utc),
            fee=Decimal("5"),
            group_id=group_id,
            leg_id=leg_id,
        )
        bridge.settle(report)
    return oms


def test_u19_ledger_builder_reconstructs_group_positions_and_unique_fill_fingerprints(tmp_path):
    store = SQLiteSettlementStore(tmp_path / "settlement.sqlite3")
    _order_with_fill(
        store, client_id="client-a", broker_id="broker-a", instrument_id="OPT-A",
        side="BUY", leg_id="inner-call",
        fills=(("exec-a1", 1, 0, "10.00"), ("exec-a2", 1, 0, "10.10")),
    )
    _order_with_fill(
        store, client_id="client-b", broker_id="broker-b", instrument_id="OPT-B",
        side="SELL", leg_id="outer-put", fills=(("exec-b1", 1, 0, "8.50"),),
    )
    _order_with_fill(
        store, client_id="client-other", broker_id="broker-other", instrument_id="OPT-X",
        side="BUY", leg_id="other-leg", group_id="OTHER:GROUP",
        fills=(("exec-other", 1, 0, "3.00"),),
    )

    snapshot = ValidationOnlyU19LedgerSnapshotBuilder(store).build(
        group_id=GROUP_ID, snapshot_id="ledger-rebuilt-1", as_of=AS_OF
    )
    assert snapshot.source == "VALIDATION_ONLY:EXECUTION_LEDGER"
    assert snapshot.complete is True
    assert snapshot.positions == (
        U19Position("OPT-A", Decimal("2")),
        U19Position("OPT-B", Decimal("-1")),
    )
    assert tuple(event.execution_id for event in snapshot.execution_events) == (
        "exec-a1", "exec-a2", "exec-b1"
    )
    assert len({event.fingerprint for event in snapshot.execution_events}) == 3
    assert snapshot.pending_order_ids == ()


def test_u19_recovery_from_persisted_ledger_still_gates_open_inbox_after_restart(tmp_path):
    store_path = tmp_path / "settlement.sqlite3"
    store = SQLiteSettlementStore(store_path)
    _order_with_fill(
        store, client_id="client-a", broker_id="broker-a", instrument_id="OPT-A",
        side="BUY", leg_id="inner-call", fills=(("exec-a1", 1, 0, "10.00"),),
    )
    store.record_late_fill_pending(
        execution_id="exec-late-a",
        client_order_id="client-a",
        broker_order_id="broker-a",
        payload={"execution_id": "exec-late-a", "group_id": GROUP_ID, "leg_id": "inner-call"},
    )
    builder = ValidationOnlyU19LedgerSnapshotBuilder(store)
    ledger = builder.build(group_id=GROUP_ID, snapshot_id="ledger-with-late-fill", as_of=AS_OF)
    assert ledger.pending_order_ids == ("client-a",)

    restarted_store = SQLiteSettlementStore(store_path)
    restarted_builder = ValidationOnlyU19LedgerSnapshotBuilder(restarted_store)
    coordinator = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(tmp_path / "u19.sqlite3"), settlement_store=restarted_store
    )
    broker_view = U19BrokerPositionSnapshot(
        group_id=GROUP_ID,
        snapshot_id="broker-matching-ledger",
        as_of=AS_OF,
        source="VALIDATION_ONLY:BROKER_EXCHANGE",
        positions=ledger.positions,
        complete=True,
        capability_verified=True,
        payload_sha256="a" * 64,
    )
    decision = coordinator.recover_from_settlement_store(
        group_id=GROUP_ID,
        broker_snapshot=broker_view,
        snapshot_id="ledger-rebuilt-after-restart",
        as_of=AS_OF,
        ledger_snapshot_builder=restarted_builder,
    )
    assert decision.status is U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED
    assert decision.restore_allowed is False
    assert decision.pending_order_ids == ("client-a",)


def test_u19_ledger_builder_rejects_missing_order_command_lineage(tmp_path):
    store = SQLiteSettlementStore(tmp_path / "missing-lineage.sqlite3")
    store.commit_fill(
        execution_id="exec-orphan",
        client_order_id="orphan-client",
        broker_order_id="orphan-broker",
        report_payload={
            "execution_id": "exec-orphan", "status": "FILLED", "filled_quantity": 1,
            "execution_price": "1.00", "execution_timestamp": AS_OF.isoformat(),
            "group_id": GROUP_ID, "leg_id": "leg-1",
        },
        order_state_payload={"client_order_id": "orphan-client"},
        position_payload={"instrument_id": "OPT-ORPHAN", "side": "BUY", "qty": 1, "avg_price": "1.00"},
        instrument_id="OPT-ORPHAN",
    )
    with pytest.raises(U19LedgerSnapshotBuildError, match="U19_EXECUTION_ORDER_COMMAND_LINEAGE_MISSING"):
        ValidationOnlyU19LedgerSnapshotBuilder(store).build(
            group_id=GROUP_ID, snapshot_id="ledger-orphan", as_of=AS_OF
        )


def test_u19_ledger_builder_rejects_future_execution_relative_to_snapshot(tmp_path):
    store = SQLiteSettlementStore(tmp_path / "future-event.sqlite3")
    _order_with_fill(
        store, client_id="client-a", broker_id="broker-a", instrument_id="OPT-A",
        side="BUY", leg_id="inner-call", fills=(("exec-a1", 1, 0, "10.00"),),
    )
    with pytest.raises(U19LedgerSnapshotBuildError, match="U19_EXECUTION_AFTER_LEDGER_AS_OF"):
        ValidationOnlyU19LedgerSnapshotBuilder(store).build(
            group_id=GROUP_ID,
            snapshot_id="ledger-before-fill",
            as_of=datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc),
        )


def test_u19_ledger_builder_promotes_unknown_inbox_order_to_global_gate(tmp_path):
    store = SQLiteSettlementStore(tmp_path / "unknown-inbox.sqlite3")
    store.record_late_fill_pending(
        execution_id="exec-unknown-order",
        client_order_id="client-order-not-in-oms",
        broker_order_id="broker-order-not-in-oms",
        payload={"execution_id": "exec-unknown-order", "source": "VALIDATION_ONLY"},
    )
    snapshot = ValidationOnlyU19LedgerSnapshotBuilder(store).build(
        group_id=GROUP_ID, snapshot_id="ledger-global-gate", as_of=AS_OF
    )
    assert snapshot.pending_order_ids == ("__GLOBAL_RECONCILIATION__",)



def test_u19_builder_preserves_cancelled_original_and_replacement_order_lineage(tmp_path):
    store = SQLiteSettlementStore(tmp_path / "replacement-lineage.sqlite3")
    original_oms = _order_with_fill(
        store, client_id="client-original", broker_id="broker-original", instrument_id="OPT-SAME",
        side="BUY", leg_id="inner-call", fills=(("exec-original-1", 1, 0, "10.00"),),
        order_quantity=3,
    )
    cancelled = original_oms.apply_cancel(ExecutionReport(
        client_order_id="client-original",
        broker_order_id="broker-original",
        execution_id="cancel-ack-fixture-1",
        status="CANCELLED",
        filled_quantity=0,
        remaining_quantity=2,
        execution_price=None,
        execution_timestamp=AS_OF,
        group_id=GROUP_ID,
        leg_id="inner-call",
    ))
    assert cancelled.status == "CANCELLED"
    _order_with_fill(
        store, client_id="client-replacement", broker_id="broker-replacement", instrument_id="OPT-SAME",
        side="BUY", leg_id="inner-call", fills=(("exec-replacement-1", 1, 0, "10.20"),),
        order_quantity=2,
    )
    assert store.record_order_replacement_link(
        link_id="lineage-fixture-1",
        original_client_order_id="client-original",
        original_broker_order_id="broker-original",
        replacement_client_order_id="client-replacement",
        replacement_broker_order_id="broker-replacement",
        group_id=GROUP_ID,
        leg_id="inner-call",
        cancel_request_ref="VALIDATION_ONLY:cancel-request-1",
        cancel_ack_ref="VALIDATION_ONLY:cancel-ack-1",
        source="VALIDATION_ONLY:ORDER_REPLACEMENT_FIXTURE",
        payload={"reason": "replacement after partial fill and cancel acknowledgement"},
    ) is True

    snapshot = ValidationOnlyU19LedgerSnapshotBuilder(store).build(
        group_id=GROUP_ID, snapshot_id="ledger-replacement-linked", as_of=AS_OF
    )
    assert snapshot.positions == (U19Position("OPT-SAME", Decimal("2")),)
    assert {event.execution_id for event in snapshot.execution_events} == {
        "exec-original-1", "exec-replacement-1"
    }
    assert snapshot.pending_order_ids == ()


def test_u19_builder_rejects_multiple_orders_for_same_leg_without_link(tmp_path):
    store = SQLiteSettlementStore(tmp_path / "replacement-missing-link.sqlite3")
    _order_with_fill(
        store, client_id="client-original", broker_id="broker-original", instrument_id="OPT-SAME",
        side="BUY", leg_id="inner-call", fills=(("exec-original-1", 1, 0, "10.00"),),
    )
    _order_with_fill(
        store, client_id="client-replacement", broker_id="broker-replacement", instrument_id="OPT-SAME",
        side="BUY", leg_id="inner-call", fills=(("exec-replacement-1", 1, 0, "10.20"),),
    )
    with pytest.raises(U19LedgerSnapshotBuildError, match="U19_MULTIPLE_ORDERS_FOR_LEG_WITHOUT_REPLACEMENT_LINEAGE"):
        ValidationOnlyU19LedgerSnapshotBuilder(store).build(
            group_id=GROUP_ID, snapshot_id="ledger-missing-replacement-link", as_of=AS_OF
        )


def test_u19_builder_rejects_replacement_link_leg_or_instrument_conflict(tmp_path):
    store = SQLiteSettlementStore(tmp_path / "replacement-conflict.sqlite3")
    original_oms = _order_with_fill(
        store, client_id="client-original", broker_id="broker-original", instrument_id="OPT-SAME",
        side="BUY", leg_id="inner-call", fills=(("exec-original-1", 1, 0, "10.00"),),
        order_quantity=2,
    )
    original_oms.apply_cancel(ExecutionReport(
        client_order_id="client-original", broker_order_id="broker-original",
        execution_id="cancel-ack-fixture-2", status="CANCELLED", filled_quantity=0,
        remaining_quantity=1, execution_price=None, execution_timestamp=AS_OF,
        group_id=GROUP_ID, leg_id="inner-call",
    ))
    _order_with_fill(
        store, client_id="client-replacement", broker_id="broker-replacement", instrument_id="OPT-DIFFERENT",
        side="BUY", leg_id="outer-call", fills=(("exec-replacement-1", 1, 0, "10.20"),),
    )
    store.record_order_replacement_link(
        link_id="lineage-conflict-1",
        original_client_order_id="client-original", original_broker_order_id="broker-original",
        replacement_client_order_id="client-replacement", replacement_broker_order_id="broker-replacement",
        group_id=GROUP_ID, leg_id="inner-call",
        cancel_request_ref="VALIDATION_ONLY:cancel-request-2",
        cancel_ack_ref="VALIDATION_ONLY:cancel-ack-2",
        source="VALIDATION_ONLY:ORDER_REPLACEMENT_FIXTURE", payload={},
    )
    with pytest.raises(U19LedgerSnapshotBuildError, match="U19_REPLACEMENT_ORDER_LINEAGE_IDENTITY_CONFLICT"):
        ValidationOnlyU19LedgerSnapshotBuilder(store).build(
            group_id=GROUP_ID, snapshot_id="ledger-replacement-conflict", as_of=AS_OF
        )



def test_order_replacement_lineage_is_append_only(tmp_path):
    store = SQLiteSettlementStore(tmp_path / "replacement-append-only.sqlite3")
    store.record_order_replacement_link(
        link_id="lineage-append-only",
        original_client_order_id="old-client",
        original_broker_order_id="old-broker",
        replacement_client_order_id="new-client",
        replacement_broker_order_id="new-broker",
        group_id=GROUP_ID,
        leg_id="inner-call",
        cancel_request_ref="VALIDATION_ONLY:cancel-request",
        cancel_ack_ref="VALIDATION_ONLY:cancel-ack",
        source="VALIDATION_ONLY:ORDER_REPLACEMENT_FIXTURE",
        payload={},
    )
    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="ORDER_REPLACEMENT_LINKS_APPEND_ONLY"):
            connection.execute("UPDATE order_replacement_links SET leg_id='other' WHERE link_id='lineage-append-only'")
        with pytest.raises(sqlite3.IntegrityError, match="ORDER_REPLACEMENT_LINKS_APPEND_ONLY"):
            connection.execute("DELETE FROM order_replacement_links WHERE link_id='lineage-append-only'")



def test_replacement_chain_late_fill_reconciles_once_into_group_ledger_and_position(tmp_path):
    store = SQLiteSettlementStore(tmp_path / "replacement-late-fill.sqlite3")
    shared_position = LivePositionAggregate("OPT-SAME")
    original_oms = _order_with_fill(
        store, client_id="client-original", broker_id="broker-original", instrument_id="OPT-SAME",
        side="BUY", leg_id="inner-call", fills=(("exec-original-1", 1, 0, "10.00"),),
        order_quantity=3, position_aggregate=shared_position,
    )
    original_oms.apply_cancel(ExecutionReport(
        client_order_id="client-original", broker_order_id="broker-original",
        execution_id="cancel-ack-late-fill-fixture", status="CANCELLED", filled_quantity=0,
        remaining_quantity=2, execution_price=None, execution_timestamp=AS_OF,
        group_id=GROUP_ID, leg_id="inner-call",
    ))
    _order_with_fill(
        store, client_id="client-replacement", broker_id="broker-replacement", instrument_id="OPT-SAME",
        side="BUY", leg_id="inner-call", fills=(("exec-replacement-1", 1, 0, "10.20"),),
        order_quantity=2, position_aggregate=shared_position,
    )
    store.record_order_replacement_link(
        link_id="lineage-late-fill-1",
        original_client_order_id="client-original", original_broker_order_id="broker-original",
        replacement_client_order_id="client-replacement", replacement_broker_order_id="broker-replacement",
        group_id=GROUP_ID, leg_id="inner-call",
        cancel_request_ref="VALIDATION_ONLY:cancel-request-late-1",
        cancel_ack_ref="VALIDATION_ONLY:cancel-ack-late-1",
        source="VALIDATION_ONLY:ORDER_REPLACEMENT_FIXTURE", payload={},
    )

    late_fill = ExecutionReport(
        client_order_id="client-original", broker_order_id="broker-original",
        execution_id="exec-original-late", status="PARTIALLY_FILLED", filled_quantity=1,
        remaining_quantity=1, execution_price=Decimal("10.10"),
        execution_timestamp=datetime(2026, 11, 18, 9, 40, tzinfo=timezone.utc),
        fee=Decimal("5"), group_id=GROUP_ID, leg_id="inner-call",
    )
    bridge = LiveExecutionPositionBridge(
        order_state_machine=original_oms,
        position_fill_adapter=LivePositionFillAdapter(shared_position),
        execution_event_deduplicator=ExecutionEventDeduplicator(persistence_store=store),
        position_aggregate=shared_position,
        settlement_store=store,
    )
    with pytest.raises(OrderStateTransitionError, match="RECONCILIATION_PENDING"):
        bridge.settle(late_fill)

    pending_ledger = ValidationOnlyU19LedgerSnapshotBuilder(store).build(
        group_id=GROUP_ID, snapshot_id="replacement-before-late-reconcile", as_of=AS_OF
    )
    assert pending_ledger.positions == (U19Position("OPT-SAME", Decimal("2")),)
    assert pending_ledger.pending_order_ids == ("client-original",)
    assert shared_position.qty == 2

    reconciled_state = bridge.settle_authoritatively_reconciled_fill(
        late_fill,
        authoritative_evidence_ref="TEST_ONLY:broker-inquiry:original-late-fill",
    )
    assert reconciled_state.status == "CANCELLED"
    assert reconciled_state.filled_quantity == 2
    assert shared_position.qty == 3

    final_ledger = ValidationOnlyU19LedgerSnapshotBuilder(SQLiteSettlementStore(store.path)).build(
        group_id=GROUP_ID, snapshot_id="replacement-after-late-reconcile", as_of=AS_OF
    )
    assert final_ledger.positions == (U19Position("OPT-SAME", Decimal("3")),)
    assert final_ledger.pending_order_ids == ()
    assert {event.execution_id for event in final_ledger.execution_events} == {
        "exec-original-1", "exec-replacement-1", "exec-original-late"
    }
    persisted_position = store.load_position_state("OPT-SAME")
    assert persisted_position["qty"] == 3
    coordinator = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(tmp_path / "u19-after-replacement-late-fill.sqlite3"),
        settlement_store=store,
    )
    broker_snapshot = U19BrokerPositionSnapshot(
        group_id=GROUP_ID,
        snapshot_id="broker-after-replacement-late-fill",
        as_of=AS_OF,
        source="VALIDATION_ONLY:BROKER_EXCHANGE",
        positions=final_ledger.positions,
        complete=True,
        capability_verified=True,
        payload_sha256="c" * 64,
    )
    decision = coordinator.recover_from_settlement_store(
        group_id=GROUP_ID,
        broker_snapshot=broker_snapshot,
        snapshot_id="ledger-after-replacement-late-fill",
        as_of=AS_OF,
        ledger_snapshot_builder=ValidationOnlyU19LedgerSnapshotBuilder(store),
    )
    assert decision.status is U19RecoveryStatus.RESTORE_ALLOWED
    assert decision.positions == final_ledger.positions
    assert decision.new_entry_enabled is False
    assert decision.order_submission_enabled is False
    journal = store.load_execution_journal_records()
    assert len(journal) == 3
    assert sum(Decimal(row["report"]["fee"]) for row in journal) == Decimal("15")

    # Replay after restart must not alter order quantity, Position, fee journal, or U19 event set.
    restarted_oms = OrderStateMachine(persistence_store=store)
    restarted_oms.restore_from_store()
    restarted_position = LivePositionAggregate("OPT-SAME")
    restarted_position.restore_persistence_record(store.load_position_state("OPT-SAME"))
    restarted_bridge = LiveExecutionPositionBridge(
        order_state_machine=restarted_oms,
        position_fill_adapter=LivePositionFillAdapter(restarted_position),
        execution_event_deduplicator=ExecutionEventDeduplicator(persistence_store=store),
        position_aggregate=restarted_position,
        settlement_store=store,
    )
    before = restarted_bridge.settle(late_fill)
    assert before.filled_quantity == 2
    assert restarted_position.qty == 3
    assert len(store.load_execution_journal_records()) == 3

def test_fresh33_sqlite_late_fill_inbox_restart_and_u19_recovery_are_integrated(tmp_path):
    store_path = tmp_path / "fresh33-settlement.sqlite3"
    instrument_id = "SYNTHETIC_CONTRACT:FRESH33:OPTION:CALL"
    client_id = "FRESH33-CLIENT-ORDER"
    broker_id = "FRESH33-BROKER-ORDER"
    group_id = "SYNTHETIC:GROUP:FRESH33-LATE-FILL"
    position = LivePositionAggregate(instrument_id)

    oms = _order_with_fill(
        SQLiteSettlementStore(store_path),
        client_id=client_id,
        broker_id=broker_id,
        instrument_id=instrument_id,
        side="BUY",
        leg_id="FRESH33-CALL",
        group_id=group_id,
        fills=(("SYNTHETIC:FRESH33:EXEC:ENTRY-1", 1, 0, "10.00"),),
        order_quantity=3,
        position_aggregate=position,
    )
    cancel_ack = ExecutionReport(
        client_order_id=client_id,
        broker_order_id=broker_id,
        execution_id=None,
        status="CANCELLED",
        filled_quantity=0,
        remaining_quantity=2,
        execution_price=None,
        execution_timestamp=datetime(2026, 11, 18, 9, 35, tzinfo=timezone.utc),
        group_id=group_id,
        leg_id="FRESH33-CALL",
    )
    oms.apply_cancel(cancel_ack)

    bridge = LiveExecutionPositionBridge(
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(position),
        execution_event_deduplicator=ExecutionEventDeduplicator(
            persistence_store=SQLiteSettlementStore(store_path)
        ),
        position_aggregate=position,
        settlement_store=SQLiteSettlementStore(store_path),
    )
    late_fill = ExecutionReport(
        client_order_id=client_id,
        broker_order_id=broker_id,
        execution_id="SYNTHETIC:FRESH33:EXEC:LATE-1",
        status="PARTIALLY_FILLED",
        filled_quantity=1,
        remaining_quantity=1,
        execution_price=Decimal("10.25"),
        execution_timestamp=datetime(2026, 11, 18, 9, 40, tzinfo=timezone.utc),
        fee=Decimal("5"),
        group_id=group_id,
        leg_id="FRESH33-CALL",
    )

    # A cancelled order's late fill is durable but not yet a settled execution.
    for _ in range(2):
        with pytest.raises(OrderStateTransitionError, match="RECONCILIATION_PENDING"):
            bridge.settle(late_fill)
    pending_store = SQLiteSettlementStore(store_path)
    pending_events = pending_store.pending_reconciliation_events(scope_key=client_id)
    assert len(pending_events) == 1
    assert pending_events[0]["execution_id"] == late_fill.execution_id
    assert pending_events[0]["payload"]["source_authority"] == "UNVERIFIED_PENDING_RECONCILIATION"
    assert pending_store.has_unresolved_reconciliation()
    assert not pending_store.has_execution(late_fill.execution_id)
    assert pending_store.load_position_state(instrument_id)["qty"] == 1

    # Reopen the SQLite database and rebuild only persisted OMS/position state.
    restarted_store = SQLiteSettlementStore(store_path)
    restarted_oms = OrderStateMachine(persistence_store=restarted_store)
    restarted_oms.restore_from_store()
    restarted_position = LivePositionAggregate(instrument_id)
    restarted_position.restore_persistence_record(
        restarted_store.load_position_state(instrument_id)
    )
    restarted_bridge = LiveExecutionPositionBridge(
        order_state_machine=restarted_oms,
        position_fill_adapter=LivePositionFillAdapter(restarted_position),
        execution_event_deduplicator=ExecutionEventDeduplicator(
            persistence_store=restarted_store
        ),
        position_aggregate=restarted_position,
        settlement_store=restarted_store,
    )
    assert restarted_oms.get(client_id).status == "CANCELLED"
    assert restarted_oms.get(client_id).filled_quantity == 1
    assert restarted_position.qty == 1
    with pytest.raises(OrderStateTransitionError, match="RECONCILIATION_PENDING"):
        restarted_bridge.settle(late_fill)

    builder = ValidationOnlyU19LedgerSnapshotBuilder(restarted_store)
    pending_ledger = builder.build(
        group_id=group_id,
        snapshot_id="FRESH33-LEDGER-PENDING-AFTER-RESTART",
        as_of=AS_OF,
    )
    assert pending_ledger.positions == (U19Position(instrument_id, Decimal("1")),)
    assert pending_ledger.pending_order_ids == (client_id,)
    coordinator = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(tmp_path / "fresh33-u19.sqlite3"),
        settlement_store=restarted_store,
    )
    pending_broker_proxy = U19BrokerPositionSnapshot(
        group_id=group_id,
        snapshot_id="FRESH33-VSSF-PROXY-PENDING",
        as_of=AS_OF,
        source="VALIDATION_ONLY:BROKER_EXCHANGE",
        positions=pending_ledger.positions,
        complete=True,
        capability_verified=True,
        payload_sha256="a" * 64,
    )
    pending_decision = coordinator.recover_from_settlement_store(
        group_id=group_id,
        broker_snapshot=pending_broker_proxy,
        snapshot_id="FRESH33-U19-PENDING-RESTART",
        as_of=AS_OF,
        ledger_snapshot_builder=builder,
    )
    assert pending_decision.status is U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED
    assert pending_decision.restore_allowed is False
    assert pending_decision.pending_order_ids == (client_id,)
    assert pending_decision.new_entry_enabled is False
    assert pending_decision.order_submission_enabled is False

    # Resolve one individually identified late fill using explicitly synthetic
    # validation evidence; this is not an external KIS/broker inquiry.
    reconciled_state = restarted_bridge.settle_authoritatively_reconciled_fill(
        late_fill,
        authoritative_evidence_ref=(
            "VALIDATION_ONLY:SYNTHETIC_RECONCILIATION_FIXTURE:FRESH33-LATE-1"
        ),
    )
    assert reconciled_state.status == "CANCELLED"
    assert reconciled_state.filled_quantity == 2
    assert restarted_position.qty == 2
    assert restarted_store.pending_reconciliation_events(scope_key=client_id) == ()
    assert not restarted_store.has_unresolved_reconciliation()

    final_store = SQLiteSettlementStore(store_path)
    final_ledger = ValidationOnlyU19LedgerSnapshotBuilder(final_store).build(
        group_id=group_id,
        snapshot_id="FRESH33-LEDGER-SETTLED-AFTER-RESTART",
        as_of=AS_OF,
    )
    assert final_ledger.positions == (U19Position(instrument_id, Decimal("2")),)
    assert final_ledger.pending_order_ids == ()
    assert {event.execution_id for event in final_ledger.execution_events} == {
        "SYNTHETIC:FRESH33:EXEC:ENTRY-1",
        late_fill.execution_id,
    }
    journal = final_store.load_execution_journal_records()
    assert len(journal) == 2
    assert sum(Decimal(row["report"]["fee"]) for row in journal) == Decimal("10")
    assert final_store.load_position_state(instrument_id)["qty"] == 2

    final_coordinator = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(tmp_path / "fresh33-u19.sqlite3"),
        settlement_store=final_store,
    )
    final_broker_proxy = U19BrokerPositionSnapshot(
        group_id=group_id,
        snapshot_id="FRESH33-VSSF-PROXY-SETTLED",
        as_of=AS_OF,
        source="VALIDATION_ONLY:BROKER_EXCHANGE",
        positions=final_ledger.positions,
        complete=True,
        capability_verified=True,
        payload_sha256="b" * 64,
    )
    final_decision = final_coordinator.recover_from_settlement_store(
        group_id=group_id,
        broker_snapshot=final_broker_proxy,
        snapshot_id="FRESH33-U19-SETTLED-AFTER-RESTART",
        as_of=AS_OF,
        ledger_snapshot_builder=ValidationOnlyU19LedgerSnapshotBuilder(final_store),
    )
    assert final_decision.status is U19RecoveryStatus.RESTORE_ALLOWED
    assert final_decision.positions == final_ledger.positions
    assert final_decision.pending_order_ids == ()
    assert final_decision.new_entry_enabled is False
    assert final_decision.order_submission_enabled is False

    # A second process/store reopen preserves the settled projection and replay is idempotent.
    last_store = SQLiteSettlementStore(store_path)
    last_oms = OrderStateMachine(persistence_store=last_store)
    last_oms.restore_from_store()
    last_position = LivePositionAggregate(instrument_id)
    last_position.restore_persistence_record(last_store.load_position_state(instrument_id))
    last_bridge = LiveExecutionPositionBridge(
        order_state_machine=last_oms,
        position_fill_adapter=LivePositionFillAdapter(last_position),
        execution_event_deduplicator=ExecutionEventDeduplicator(
            persistence_store=last_store
        ),
        position_aggregate=last_position,
        settlement_store=last_store,
    )
    replay_state = last_bridge.settle(late_fill)
    assert replay_state.filled_quantity == 2
    assert last_oms.get(client_id).status == "CANCELLED"
    assert last_position.qty == 2
    assert len(last_store.load_execution_journal_records()) == 2
    assert sum(
        Decimal(row["report"]["fee"])
        for row in last_store.load_execution_journal_records()
    ) == Decimal("10")
    assert last_store.pending_reconciliation_events(scope_key=client_id) == ()
    assert not last_store.has_unresolved_reconciliation()
    latest_u19 = SqliteTrack2U19RecoveryStore(
        tmp_path / "fresh33-u19.sqlite3"
    ).load_latest(group_id)
    assert latest_u19["status"] == U19RecoveryStatus.RESTORE_ALLOWED.value
    assert latest_u19["new_entry_enabled"] is False
    assert latest_u19["order_submission_enabled"] is False


def test_fresh33_conflicting_late_fill_survives_restart_and_keeps_u19_gated(tmp_path):
    from environments.live.settlement.sqlite_settlement_store import SettlementStoreError

    store_path = tmp_path / "fresh33-conflict-settlement.sqlite3"
    instrument_id = "SYNTHETIC_CONTRACT:FRESH33:OPTION:PUT"
    client_id = "FRESH33-CONFLICT-CLIENT"
    broker_id = "FRESH33-CONFLICT-BROKER"
    group_id = "SYNTHETIC:GROUP:FRESH33-CONFLICT"
    position = LivePositionAggregate(instrument_id)
    oms = _order_with_fill(
        SQLiteSettlementStore(store_path),
        client_id=client_id,
        broker_id=broker_id,
        instrument_id=instrument_id,
        side="BUY",
        leg_id="FRESH33-PUT",
        group_id=group_id,
        fills=(("SYNTHETIC:FRESH33:EXEC:CONFLICT-ENTRY", 1, 0, "9.50"),),
        order_quantity=3,
        position_aggregate=position,
    )
    oms.apply_cancel(ExecutionReport(
        client_order_id=client_id,
        broker_order_id=broker_id,
        execution_id=None,
        status="CANCELLED",
        filled_quantity=0,
        remaining_quantity=2,
        execution_price=None,
        execution_timestamp=datetime(2026, 11, 18, 9, 35, tzinfo=timezone.utc),
        group_id=group_id,
        leg_id="FRESH33-PUT",
    ))
    store = SQLiteSettlementStore(store_path)
    bridge = LiveExecutionPositionBridge(
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(position),
        execution_event_deduplicator=ExecutionEventDeduplicator(persistence_store=store),
        position_aggregate=position,
        settlement_store=store,
    )
    late_fill = ExecutionReport(
        client_order_id=client_id,
        broker_order_id=broker_id,
        execution_id="SYNTHETIC:FRESH33:EXEC:CONFLICT-LATE",
        status="PARTIALLY_FILLED",
        filled_quantity=1,
        remaining_quantity=1,
        execution_price=Decimal("9.60"),
        execution_timestamp=datetime(2026, 11, 18, 9, 40, tzinfo=timezone.utc),
        fee=Decimal("5"),
        group_id=group_id,
        leg_id="FRESH33-PUT",
    )
    with pytest.raises(OrderStateTransitionError, match="RECONCILIATION_PENDING"):
        bridge.settle(late_fill)
    conflicting = ExecutionReport(
        client_order_id=client_id,
        broker_order_id=broker_id,
        execution_id=late_fill.execution_id,
        status="PARTIALLY_FILLED",
        filled_quantity=1,
        remaining_quantity=1,
        execution_price=Decimal("9.70"),
        execution_timestamp=late_fill.execution_timestamp,
        fee=Decimal("5"),
        group_id=group_id,
        leg_id="FRESH33-PUT",
    )
    with pytest.raises(SettlementStoreError, match="RECONCILIATION_INBOX_EXECUTION_ID_COLLISION"):
        bridge.settle(conflicting)

    restarted_store = SQLiteSettlementStore(store_path)
    unresolved = restarted_store.unresolved_reconciliations()
    assert len(unresolved) == 1
    assert unresolved[0]["status"] == "CONFLICT"
    assert unresolved[0]["reason"] == "RECONCILIATION_INBOX_EXECUTION_ID_COLLISION"
    assert len(restarted_store.open_reconciliation_events(scope_key=client_id)) == 1
    restarted_oms = OrderStateMachine(persistence_store=restarted_store)
    restarted_oms.restore_from_store()
    restarted_position = LivePositionAggregate(instrument_id)
    restarted_position.restore_persistence_record(
        restarted_store.load_position_state(instrument_id)
    )
    assert restarted_oms.get(client_id).status == "CANCELLED"
    assert restarted_oms.get(client_id).filled_quantity == 1
    assert restarted_position.qty == 1
    assert len(restarted_store.load_execution_journal_records()) == 1

    builder = ValidationOnlyU19LedgerSnapshotBuilder(restarted_store)
    ledger = builder.build(
        group_id=group_id,
        snapshot_id="FRESH33-CONFLICT-LEDGER-AFTER-RESTART",
        as_of=AS_OF,
    )
    assert ledger.positions == (U19Position(instrument_id, Decimal("1")),)
    assert ledger.pending_order_ids == (client_id,)
    coordinator = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(tmp_path / "fresh33-conflict-u19.sqlite3"),
        settlement_store=restarted_store,
    )
    decision = coordinator.recover_from_settlement_store(
        group_id=group_id,
        broker_snapshot=U19BrokerPositionSnapshot(
            group_id=group_id,
            snapshot_id="FRESH33-CONFLICT-BROKER-PROXY",
            as_of=AS_OF,
            source="VALIDATION_ONLY:BROKER_EXCHANGE",
            positions=ledger.positions,
            complete=True,
            capability_verified=True,
            payload_sha256="c" * 64,
        ),
        snapshot_id="FRESH33-CONFLICT-U19-AFTER-RESTART",
        as_of=AS_OF,
        ledger_snapshot_builder=builder,
    )
    assert decision.status is U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED
    assert decision.restore_allowed is False
    assert decision.pending_order_ids == (client_id,)
    assert decision.new_entry_enabled is False
    assert decision.order_submission_enabled is False
    assert restarted_store.unresolved_reconciliations()[0]["status"] == "CONFLICT"
