from datetime import datetime, timezone
from dataclasses import replace
import hashlib
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


@pytest.mark.parametrize(
    "failure_point,trigger_sql",
    [
        (
            "execution_journal_insert",
            """
            CREATE TRIGGER inject_fresh34_journal_failure
            BEFORE INSERT ON execution_journal
            WHEN NEW.execution_id='SYNTHETIC:FRESH34:EXEC:LATE'
            BEGIN SELECT RAISE(ABORT, 'FRESH34_JOURNAL_FAILURE'); END;
            """,
        ),
        (
            "oms_order_projection",
            """
            CREATE TRIGGER inject_fresh34_order_failure
            BEFORE UPDATE ON order_states
            WHEN OLD.client_order_id='FRESH34-CLIENT'
            BEGIN SELECT RAISE(ABORT, 'FRESH34_ORDER_FAILURE'); END;
            """,
        ),
        (
            "position_projection",
            """
            CREATE TRIGGER inject_fresh34_position_failure
            BEFORE UPDATE ON position_states
            WHEN OLD.instrument_id='SYNTHETIC_CONTRACT:FRESH34:OPTION:CALL'
            BEGIN SELECT RAISE(ABORT, 'FRESH34_POSITION_FAILURE'); END;
            """,
        ),
        (
            "inbox_resolution",
            """
            CREATE TRIGGER inject_fresh34_inbox_failure
            BEFORE UPDATE ON reconciliation_inbox
            WHEN OLD.execution_id='SYNTHETIC:FRESH34:EXEC:LATE'
            BEGIN SELECT RAISE(ABORT, 'FRESH34_INBOX_FAILURE'); END;
            """,
        ),
    ],
)
def test_fresh34_late_fill_settlement_sqlite_failures_rollback_and_keep_u19_gated(
    tmp_path, failure_point, trigger_sql
):
    store_path = tmp_path / f"fresh34-{failure_point}.sqlite3"
    instrument_id = "SYNTHETIC_CONTRACT:FRESH34:OPTION:CALL"
    client_id = "FRESH34-CLIENT"
    broker_id = "FRESH34-BROKER"
    group_id = "SYNTHETIC:GROUP:FRESH34-ATOMICITY"
    position = LivePositionAggregate(instrument_id)
    store = SQLiteSettlementStore(store_path)
    oms = _order_with_fill(
        store,
        client_id=client_id,
        broker_id=broker_id,
        instrument_id=instrument_id,
        side="BUY",
        leg_id="FRESH34-CALL",
        group_id=group_id,
        fills=(("SYNTHETIC:FRESH34:EXEC:ENTRY", 1, 0, "10.00"),),
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
        leg_id="FRESH34-CALL",
    ))
    bridge = LiveExecutionPositionBridge(
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(position),
        execution_event_deduplicator=ExecutionEventDeduplicator(
            persistence_store=store
        ),
        position_aggregate=position,
        settlement_store=store,
    )
    late_fill = ExecutionReport(
        client_order_id=client_id,
        broker_order_id=broker_id,
        execution_id="SYNTHETIC:FRESH34:EXEC:LATE",
        status="PARTIALLY_FILLED",
        filled_quantity=1,
        remaining_quantity=1,
        execution_price=Decimal("10.25"),
        execution_timestamp=datetime(2026, 11, 18, 9, 40, tzinfo=timezone.utc),
        fee=Decimal("5"),
        group_id=group_id,
        leg_id="FRESH34-CALL",
    )
    with pytest.raises(OrderStateTransitionError, match="RECONCILIATION_PENDING"):
        bridge.settle(late_fill)
    assert len(store.pending_reconciliation_events(scope_key=client_id)) == 1

    with sqlite3.connect(store_path) as connection:
        connection.executescript(trigger_sql)

    with pytest.raises(SettlementStoreError, match="SETTLEMENT_TRANSACTION_FAILED"):
        bridge.settle_authoritatively_reconciled_fill(
            late_fill,
            authoritative_evidence_ref=(
                "VALIDATION_ONLY:SYNTHETIC_RECONCILIATION_FIXTURE:FRESH34"
            ),
        )

    # Every failure before SQLite COMMIT rolls back journal, OMS and position
    # projections together; the original inbox item remains durable.
    assert not store.has_execution(late_fill.execution_id)
    assert len(store.load_execution_journal_records()) == 1
    assert store.load_position_state(instrument_id)["qty"] == 1
    assert oms.get(client_id).status == "CANCELLED"
    assert oms.get(client_id).filled_quantity == 1
    assert position.qty == 1
    pending = store.pending_reconciliation_events(scope_key=client_id)
    assert len(pending) == 1
    assert pending[0]["execution_id"] == late_fill.execution_id
    unresolved = store.unresolved_reconciliations()
    assert any(
        item["scope_key"] == client_id
        and item["status"] == "CONFLICT"
        and item["reason"] == "SETTLEMENT_TRANSACTION_FAILED"
        for item in unresolved
    )

    # A new process reconstructs the last committed state, not a half-applied fill.
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
    assert restarted_oms.get(client_id).filled_quantity == 1
    assert restarted_position.qty == 1
    with pytest.raises(OrderStateTransitionError, match="RECONCILIATION_PENDING"):
        restarted_bridge.settle(late_fill)
    assert len(restarted_store.load_execution_journal_records()) == 1
    assert len(restarted_store.pending_reconciliation_events(scope_key=client_id)) == 1

    builder = ValidationOnlyU19LedgerSnapshotBuilder(restarted_store)
    ledger = builder.build(
        group_id=group_id,
        snapshot_id=f"FRESH34-{failure_point}-PENDING",
        as_of=AS_OF,
    )
    assert ledger.positions == (U19Position(instrument_id, Decimal("1")),)
    assert ledger.pending_order_ids == (client_id,)
    coordinator = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(tmp_path / f"fresh34-{failure_point}-u19.sqlite3"),
        settlement_store=restarted_store,
    )
    decision = coordinator.recover_from_settlement_store(
        group_id=group_id,
        broker_snapshot=U19BrokerPositionSnapshot(
            group_id=group_id,
            snapshot_id=f"FRESH34-{failure_point}-BROKER-PROXY",
            as_of=AS_OF,
            source="VALIDATION_ONLY:BROKER_EXCHANGE",
            positions=ledger.positions,
            complete=True,
            capability_verified=True,
            payload_sha256=("d" if failure_point else "e") * 64,
        ),
        snapshot_id=f"FRESH34-{failure_point}-U19-PENDING",
        as_of=AS_OF,
        ledger_snapshot_builder=builder,
    )
    assert decision.status is U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED
    assert decision.restore_allowed is False
    assert decision.pending_order_ids == (client_id,)
    assert decision.new_entry_enabled is False
    assert decision.order_submission_enabled is False


def test_fresh34_post_commit_memory_projection_failure_rebuilds_from_sqlite_and_keeps_u19_gated(
    tmp_path, monkeypatch
):
    store_path = tmp_path / "fresh34-post-commit.sqlite3"
    instrument_id = "SYNTHETIC_CONTRACT:FRESH34:OPTION:PUT"
    client_id = "FRESH34-POST-COMMIT-CLIENT"
    broker_id = "FRESH34-POST-COMMIT-BROKER"
    group_id = "SYNTHETIC:GROUP:FRESH34-POST-COMMIT"
    position = LivePositionAggregate(instrument_id)
    store = SQLiteSettlementStore(store_path)
    oms = _order_with_fill(
        store,
        client_id=client_id,
        broker_id=broker_id,
        instrument_id=instrument_id,
        side="BUY",
        leg_id="FRESH34-PUT",
        group_id=group_id,
        fills=(("SYNTHETIC:FRESH34:EXEC:ENTRY-PUT", 1, 0, "9.00"),),
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
        leg_id="FRESH34-PUT",
    ))
    bridge = LiveExecutionPositionBridge(
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(position),
        execution_event_deduplicator=ExecutionEventDeduplicator(
            persistence_store=store
        ),
        position_aggregate=position,
        settlement_store=store,
    )
    late_fill = ExecutionReport(
        client_order_id=client_id,
        broker_order_id=broker_id,
        execution_id="SYNTHETIC:FRESH34:EXEC:POST-COMMIT",
        status="PARTIALLY_FILLED",
        filled_quantity=1,
        remaining_quantity=1,
        execution_price=Decimal("9.25"),
        execution_timestamp=datetime(2026, 11, 18, 9, 40, tzinfo=timezone.utc),
        fee=Decimal("5"),
        group_id=group_id,
        leg_id="FRESH34-PUT",
    )
    with pytest.raises(OrderStateTransitionError, match="RECONCILIATION_PENDING"):
        bridge.settle(late_fill)

    def fail_projection(_snapshot):
        raise RuntimeError("FRESH34_IN_MEMORY_POSITION_PROJECTION_FAILURE")

    monkeypatch.setattr(position, "restore_snapshot", fail_projection)
    with pytest.raises(
        RuntimeError, match="SETTLEMENT_COMMITTED_MEMORY_PROJECTION_REBUILD_REQUIRED"
    ):
        bridge.settle_authoritatively_reconciled_fill(
            late_fill,
            authoritative_evidence_ref=(
                "VALIDATION_ONLY:SYNTHETIC_RECONCILIATION_FIXTURE:FRESH34-POST-COMMIT"
            ),
        )

    # SQLite commit is atomic and complete; only the in-memory projection failed.
    assert store.has_execution(late_fill.execution_id)
    assert len(store.load_execution_journal_records()) == 2
    assert store.load_position_state(instrument_id)["qty"] == 2
    assert oms.get(client_id).filled_quantity == 2
    assert position.qty == 1
    assert store.pending_reconciliation_events(scope_key=client_id) == ()
    assert any(
        item["scope_key"] == client_id
        and item["status"] == "CONFLICT"
        and item["reason"] == "POST_COMMIT_MEMORY_PROJECTION_REBUILD_REQUIRED"
        for item in store.unresolved_reconciliations()
    )

    # Restart rebuilds both projections from the committed SQLite transaction.
    restarted_store = SQLiteSettlementStore(store_path)
    restarted_oms = OrderStateMachine(persistence_store=restarted_store)
    restarted_oms.restore_from_store()
    restarted_position = LivePositionAggregate(instrument_id)
    restarted_position.restore_persistence_record(
        restarted_store.load_position_state(instrument_id)
    )
    assert restarted_oms.get(client_id).filled_quantity == 2
    assert restarted_position.qty == 2
    assert len(restarted_store.load_execution_journal_records()) == 2
    assert restarted_store.pending_reconciliation_events(scope_key=client_id) == ()
    assert restarted_store.has_unresolved_reconciliation()

    builder = ValidationOnlyU19LedgerSnapshotBuilder(restarted_store)
    ledger = builder.build(
        group_id=group_id,
        snapshot_id="FRESH34-POST-COMMIT-REBUILT",
        as_of=AS_OF,
    )
    assert ledger.positions == (U19Position(instrument_id, Decimal("2")),)
    assert ledger.pending_order_ids == (client_id,)
    coordinator = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(tmp_path / "fresh34-post-commit-u19.sqlite3"),
        settlement_store=restarted_store,
    )
    decision = coordinator.recover_from_settlement_store(
        group_id=group_id,
        broker_snapshot=U19BrokerPositionSnapshot(
            group_id=group_id,
            snapshot_id="FRESH34-POST-COMMIT-BROKER-PROXY",
            as_of=AS_OF,
            source="VALIDATION_ONLY:BROKER_EXCHANGE",
            positions=ledger.positions,
            complete=True,
            capability_verified=True,
            payload_sha256="f" * 64,
        ),
        snapshot_id="FRESH34-POST-COMMIT-U19",
        as_of=AS_OF,
        ledger_snapshot_builder=builder,
    )
    assert decision.status is U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED
    assert decision.restore_allowed is False
    assert decision.new_entry_enabled is False
    assert decision.order_submission_enabled is False


def test_fresh35_settlement_commit_checkpoint_crash_window_replay_and_checkpoint_retry(
    tmp_path
):
    store_path = tmp_path / "fresh35-settlement.sqlite3"
    checkpoint_path = tmp_path / "fresh35-u19.sqlite3"
    instrument_id = "SYNTHETIC_CONTRACT:FRESH35:OPTION:CALL"
    client_id = "FRESH35-CLIENT"
    broker_id = "FRESH35-BROKER"
    group_id = "SYNTHETIC:GROUP:FRESH35-CHECKPOINT-CRASH"
    position = LivePositionAggregate(instrument_id)
    store = SQLiteSettlementStore(store_path)
    oms = _order_with_fill(
        store,
        client_id=client_id,
        broker_id=broker_id,
        instrument_id=instrument_id,
        side="BUY",
        leg_id="FRESH35-CALL",
        group_id=group_id,
        fills=(("SYNTHETIC:FRESH35:EXEC:ENTRY", 1, 0, "10.00"),),
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
        leg_id="FRESH35-CALL",
    ))
    bridge = LiveExecutionPositionBridge(
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(position),
        execution_event_deduplicator=ExecutionEventDeduplicator(
            persistence_store=store
        ),
        position_aggregate=position,
        settlement_store=store,
    )
    late_fill = ExecutionReport(
        client_order_id=client_id,
        broker_order_id=broker_id,
        execution_id="SYNTHETIC:FRESH35:EXEC:LATE",
        status="PARTIALLY_FILLED",
        filled_quantity=1,
        remaining_quantity=1,
        execution_price=Decimal("10.25"),
        execution_timestamp=datetime(2026, 11, 18, 9, 40, tzinfo=timezone.utc),
        fee=Decimal("5"),
        group_id=group_id,
        leg_id="FRESH35-CALL",
    )
    with pytest.raises(OrderStateTransitionError, match="RECONCILIATION_PENDING"):
        bridge.settle(late_fill)

    # Persist the pending U19 decision before resolving the late fill.
    pending_builder = ValidationOnlyU19LedgerSnapshotBuilder(store)
    pending_ledger = pending_builder.build(
        group_id=group_id,
        snapshot_id="FRESH35-LEDGER-PENDING",
        as_of=AS_OF,
    )
    assert pending_ledger.positions == (U19Position(instrument_id, Decimal("1")),)
    assert pending_ledger.pending_order_ids == (client_id,)
    checkpoint_store = SqliteTrack2U19RecoveryStore(checkpoint_path)
    coordinator = ValidationOnlyTrack2U19RecoveryCoordinator(
        checkpoint_store, settlement_store=store
    )
    pending_decision = coordinator.recover(
        group_id=group_id,
        broker_snapshot=U19BrokerPositionSnapshot(
            group_id=group_id,
            snapshot_id="FRESH35-BROKER-PENDING",
            as_of=AS_OF,
            source="VALIDATION_ONLY:BROKER_EXCHANGE",
            positions=pending_ledger.positions,
            complete=True,
            capability_verified=True,
            payload_sha256="a" * 64,
        ),
        ledger_snapshot=pending_ledger,
    )
    assert pending_decision.status is U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED
    pending_checkpoint = checkpoint_store.load_latest(group_id)
    assert pending_checkpoint["checkpoint_id"] == pending_decision.checkpoint_id
    assert pending_checkpoint["status"] == U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED.value

    # Settlement DB commits first. Simulate a process crash before U19 checkpoint
    # update by not invoking the coordinator in this process.
    settled = bridge.settle_authoritatively_reconciled_fill(
        late_fill,
        authoritative_evidence_ref=(
            "VALIDATION_ONLY:SYNTHETIC_RECONCILIATION_FIXTURE:FRESH35"
        ),
    )
    assert settled.filled_quantity == 2
    assert store.has_execution(late_fill.execution_id)
    assert len(store.load_execution_journal_records()) == 2
    assert store.load_position_state(instrument_id)["qty"] == 2
    assert store.pending_reconciliation_events(scope_key=client_id) == ()
    assert checkpoint_store.load_latest(group_id)["checkpoint_id"] == pending_decision.checkpoint_id

    # Restart settlement projections from SQLite. Replay is recognized as the
    # same committed event and cannot change journal, fee payload, or position.
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
    before_journal = restarted_store.load_execution_journal_records()
    replay_state = restarted_bridge.settle(late_fill)
    assert replay_state.filled_quantity == 2
    assert restarted_position.qty == 2
    assert restarted_store.load_execution_journal_records() == before_journal
    assert len(before_journal) == 2
    assert restarted_store.pending_reconciliation_events(scope_key=client_id) == ()

    final_builder = ValidationOnlyU19LedgerSnapshotBuilder(restarted_store)
    final_ledger = final_builder.build(
        group_id=group_id,
        snapshot_id="FRESH35-LEDGER-SETTLED",
        as_of=AS_OF,
    )
    assert final_ledger.positions == (U19Position(instrument_id, Decimal("2")),)
    assert final_ledger.pending_order_ids == ()

    # Fail the U19 checkpoint insert. Settlement remains committed, but the
    # previously persisted pending checkpoint remains the latest safe decision.
    with sqlite3.connect(checkpoint_path) as connection:
        connection.execute("""
            CREATE TRIGGER inject_fresh35_checkpoint_failure
            BEFORE INSERT ON track2_u19_recovery_checkpoint
            BEGIN SELECT RAISE(ABORT, 'FRESH35_CHECKPOINT_INSERT_FAILURE'); END
        """)
    restarted_coordinator = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(checkpoint_path),
        settlement_store=restarted_store,
    )
    with pytest.raises(sqlite3.IntegrityError, match="FRESH35_CHECKPOINT_INSERT_FAILURE"):
        restarted_coordinator.recover_from_settlement_store(
            group_id=group_id,
            broker_snapshot=U19BrokerPositionSnapshot(
                group_id=group_id,
                snapshot_id="FRESH35-BROKER-SETTLED",
                as_of=AS_OF,
                source="VALIDATION_ONLY:BROKER_EXCHANGE",
                positions=final_ledger.positions,
                complete=True,
                capability_verified=True,
                payload_sha256="b" * 64,
            ),
            snapshot_id="FRESH35-LEDGER-SETTLED",
            as_of=AS_OF,
            ledger_snapshot_builder=final_builder,
        )
    still_pending = SqliteTrack2U19RecoveryStore(checkpoint_path).load_latest(group_id)
    assert still_pending["checkpoint_id"] == pending_decision.checkpoint_id
    assert still_pending["status"] == U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED.value
    assert len(restarted_store.load_execution_journal_records()) == 2
    assert restarted_store.load_position_state(instrument_id)["qty"] == 2
    assert restarted_store.pending_reconciliation_events(scope_key=client_id) == ()

    # Remove the injected storage fault and retry from persisted settlement
    # evidence. The checkpoint advances only after a complete U19 evaluation.
    with sqlite3.connect(checkpoint_path) as connection:
        connection.execute("DROP TRIGGER inject_fresh35_checkpoint_failure")
    recovered_coordinator = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(checkpoint_path),
        settlement_store=restarted_store,
    )
    recovered = recovered_coordinator.recover_from_settlement_store(
        group_id=group_id,
        broker_snapshot=U19BrokerPositionSnapshot(
            group_id=group_id,
            snapshot_id="FRESH35-BROKER-SETTLED",
            as_of=AS_OF,
            source="VALIDATION_ONLY:BROKER_EXCHANGE",
            positions=final_ledger.positions,
            complete=True,
            capability_verified=True,
            payload_sha256="b" * 64,
        ),
        snapshot_id="FRESH35-LEDGER-SETTLED",
        as_of=AS_OF,
        ledger_snapshot_builder=final_builder,
    )
    assert recovered.status is U19RecoveryStatus.RESTORE_ALLOWED
    assert recovered.positions == final_ledger.positions
    assert recovered.pending_order_ids == ()
    assert recovered.new_entry_enabled is False
    assert recovered.order_submission_enabled is False
    final_checkpoint = SqliteTrack2U19RecoveryStore(checkpoint_path).load_latest(group_id)
    assert final_checkpoint["checkpoint_id"] == recovered.checkpoint_id
    assert final_checkpoint["status"] == U19RecoveryStatus.RESTORE_ALLOWED.value
    assert final_checkpoint["new_entry_enabled"] is False
    assert final_checkpoint["order_submission_enabled"] is False

    # Repeated recovery with identical snapshots is checkpoint-idempotent.
    with sqlite3.connect(checkpoint_path) as connection:
        before_count = connection.execute(
            "SELECT COUNT(*) FROM track2_u19_recovery_checkpoint WHERE group_id=?",
            (group_id,),
        ).fetchone()[0]
    repeated = recovered_coordinator.recover_from_settlement_store(
        group_id=group_id,
        broker_snapshot=U19BrokerPositionSnapshot(
            group_id=group_id,
            snapshot_id="FRESH35-BROKER-SETTLED",
            as_of=AS_OF,
            source="VALIDATION_ONLY:BROKER_EXCHANGE",
            positions=final_ledger.positions,
            complete=True,
            capability_verified=True,
            payload_sha256="b" * 64,
        ),
        snapshot_id="FRESH35-LEDGER-SETTLED",
        as_of=AS_OF,
        ledger_snapshot_builder=final_builder,
    )
    with sqlite3.connect(checkpoint_path) as connection:
        after_count = connection.execute(
            "SELECT COUNT(*) FROM track2_u19_recovery_checkpoint WHERE group_id=?",
            (group_id,),
        ).fetchone()[0]
    assert repeated.checkpoint_id == recovered.checkpoint_id
    assert after_count == before_count == 2
    assert len(restarted_store.load_execution_journal_records()) == 2
    assert restarted_position.qty == 2
    assert restarted_store.pending_reconciliation_events(scope_key=client_id) == ()


def test_fresh36_multi_late_fill_partial_settlement_restart_and_conflict_keep_u19_gated(
    tmp_path
):
    store_path = tmp_path / "fresh36-settlement.sqlite3"
    checkpoint_path = tmp_path / "fresh36-u19.sqlite3"
    instrument_id = "SYNTHETIC_CONTRACT:FRESH36:OPTION:PUT"
    client_id = "FRESH36-CLIENT"
    broker_id = "FRESH36-BROKER"
    group_id = "SYNTHETIC:GROUP:FRESH36-MULTI-LATE-FILL"
    position = LivePositionAggregate(instrument_id)
    store = SQLiteSettlementStore(store_path)
    oms = _order_with_fill(
        store,
        client_id=client_id,
        broker_id=broker_id,
        instrument_id=instrument_id,
        side="BUY",
        leg_id="FRESH36-PUT",
        group_id=group_id,
        fills=(("SYNTHETIC:FRESH36:EXEC:ENTRY", 1, 0, "9.00"),),
        order_quantity=4,
        position_aggregate=position,
    )
    oms.apply_cancel(ExecutionReport(
        client_order_id=client_id,
        broker_order_id=broker_id,
        execution_id=None,
        status="CANCELLED",
        filled_quantity=0,
        remaining_quantity=3,
        execution_price=None,
        execution_timestamp=datetime(2026, 11, 18, 9, 35, tzinfo=timezone.utc),
        group_id=group_id,
        leg_id="FRESH36-PUT",
    ))
    bridge = LiveExecutionPositionBridge(
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(position),
        execution_event_deduplicator=ExecutionEventDeduplicator(
            persistence_store=store
        ),
        position_aggregate=position,
        settlement_store=store,
    )

    late_one = ExecutionReport(
        client_order_id=client_id,
        broker_order_id=broker_id,
        execution_id="SYNTHETIC:FRESH36:EXEC:LATE-1",
        status="PARTIALLY_FILLED",
        filled_quantity=1,
        remaining_quantity=2,
        execution_price=Decimal("9.10"),
        execution_timestamp=datetime(2026, 11, 18, 9, 40, tzinfo=timezone.utc),
        fee=Decimal("5"),
        group_id=group_id,
        leg_id="FRESH36-PUT",
    )
    late_two = ExecutionReport(
        client_order_id=client_id,
        broker_order_id=broker_id,
        execution_id="SYNTHETIC:FRESH36:EXEC:LATE-2",
        status="PARTIALLY_FILLED",
        filled_quantity=1,
        remaining_quantity=1,
        execution_price=Decimal("9.15"),
        execution_timestamp=datetime(2026, 11, 18, 9, 41, tzinfo=timezone.utc),
        fee=Decimal("5"),
        group_id=group_id,
        leg_id="FRESH36-PUT",
    )
    late_three = ExecutionReport(
        client_order_id=client_id,
        broker_order_id=broker_id,
        execution_id="SYNTHETIC:FRESH36:EXEC:LATE-3",
        status="FILLED",
        filled_quantity=1,
        remaining_quantity=0,
        execution_price=Decimal("9.20"),
        execution_timestamp=datetime(2026, 11, 18, 9, 42, tzinfo=timezone.utc),
        fee=Decimal("5"),
        group_id=group_id,
        leg_id="FRESH36-PUT",
    )
    for report in (late_one, late_two, late_three):
        with pytest.raises(OrderStateTransitionError, match="RECONCILIATION_PENDING"):
            bridge.settle(report)

    # A reused execution ID with a different payload is preserved as conflict.
    conflicting_three = ExecutionReport(
        client_order_id=client_id,
        broker_order_id=broker_id,
        execution_id=late_three.execution_id,
        status="FILLED",
        filled_quantity=1,
        remaining_quantity=0,
        execution_price=Decimal("9.30"),
        execution_timestamp=late_three.execution_timestamp,
        fee=Decimal("5"),
        group_id=group_id,
        leg_id="FRESH36-PUT",
    )
    with pytest.raises(
        SettlementStoreError,
        match="RECONCILIATION_INBOX_EXECUTION_ID_COLLISION",
    ):
        bridge.settle(conflicting_three)

    inbox = store.open_reconciliation_events(scope_key=client_id)
    assert [(item["execution_id"], item["status"]) for item in inbox] == [
        (late_one.execution_id, "PENDING"),
        (late_two.execution_id, "PENDING"),
        (late_three.execution_id, "CONFLICT"),
    ]
    assert len(store.load_execution_journal_records()) == 1
    assert position.qty == 1

    # Resolve only the first event. Other pending/conflicting events must remain.
    bridge.settle_authoritatively_reconciled_fill(
        late_one,
        authoritative_evidence_ref=(
            "VALIDATION_ONLY:SYNTHETIC_RECONCILIATION_FIXTURE:FRESH36-LATE-1"
        ),
    )
    assert position.qty == 2
    assert store.has_execution(late_one.execution_id)
    assert not store.has_execution(late_two.execution_id)
    assert not store.has_execution(late_three.execution_id)
    assert [
        (item["execution_id"], item["status"])
        for item in store.open_reconciliation_events(scope_key=client_id)
    ] == [
        (late_two.execution_id, "PENDING"),
        (late_three.execution_id, "CONFLICT"),
    ]
    assert store.unresolved_reconciliations()[0]["status"] == "CONFLICT"

    # Restart between partial settlements; persisted OMS and Position must agree.
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
    assert restarted_oms.get(client_id).filled_quantity == 2
    assert restarted_position.qty == 2
    assert len(restarted_store.load_execution_journal_records()) == 2

    builder = ValidationOnlyU19LedgerSnapshotBuilder(restarted_store)
    first_ledger = builder.build(
        group_id=group_id,
        snapshot_id="FRESH36-LEDGER-AFTER-FIRST-SETTLEMENT",
        as_of=AS_OF,
    )
    assert first_ledger.positions == (U19Position(instrument_id, Decimal("2")),)
    assert first_ledger.pending_order_ids == (client_id,)
    coordinator = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(checkpoint_path),
        settlement_store=restarted_store,
    )
    first_decision = coordinator.recover_from_settlement_store(
        group_id=group_id,
        broker_snapshot=U19BrokerPositionSnapshot(
            group_id=group_id,
            snapshot_id="FRESH36-BROKER-AFTER-FIRST-SETTLEMENT",
            as_of=AS_OF,
            source="VALIDATION_ONLY:BROKER_EXCHANGE",
            positions=first_ledger.positions,
            complete=True,
            capability_verified=True,
            payload_sha256="a" * 64,
        ),
        snapshot_id="FRESH36-LEDGER-AFTER-FIRST-SETTLEMENT",
        as_of=AS_OF,
        ledger_snapshot_builder=builder,
    )
    assert first_decision.status is U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED
    assert first_decision.pending_order_ids == (client_id,)
    assert first_decision.new_entry_enabled is False
    assert first_decision.order_submission_enabled is False

    # Settle the second pending event while the third remains conflicted.
    restarted_bridge.settle_authoritatively_reconciled_fill(
        late_two,
        authoritative_evidence_ref=(
            "VALIDATION_ONLY:SYNTHETIC_RECONCILIATION_FIXTURE:FRESH36-LATE-2"
        ),
    )
    assert restarted_position.qty == 3
    assert restarted_oms.get(client_id).filled_quantity == 3
    assert restarted_store.has_execution(late_two.execution_id)
    assert not restarted_store.has_execution(late_three.execution_id)
    assert [
        (item["execution_id"], item["status"])
        for item in restarted_store.open_reconciliation_events(scope_key=client_id)
    ] == [(late_three.execution_id, "CONFLICT")]
    assert restarted_store.pending_reconciliation_events(scope_key=client_id) == ()
    assert restarted_store.unresolved_reconciliations()[0]["status"] == "CONFLICT"

    # Identical replay of both settled events is idempotent after restart.
    journal_before_replay = restarted_store.load_execution_journal_records()
    replay_one = restarted_bridge.settle(late_one)
    replay_two = restarted_bridge.settle(late_two)
    assert replay_one.filled_quantity == 3
    assert replay_two.filled_quantity == 3
    assert restarted_position.qty == 3
    assert restarted_store.load_execution_journal_records() == journal_before_replay
    assert len(journal_before_replay) == 3

    final_ledger = builder.build(
        group_id=group_id,
        snapshot_id="FRESH36-LEDGER-SECOND-SETTLEMENT-CONFLICT-REMAINS",
        as_of=AS_OF,
    )
    assert final_ledger.positions == (U19Position(instrument_id, Decimal("3")),)
    assert final_ledger.pending_order_ids == (client_id,)
    final_decision = coordinator.recover_from_settlement_store(
        group_id=group_id,
        broker_snapshot=U19BrokerPositionSnapshot(
            group_id=group_id,
            snapshot_id="FRESH36-BROKER-SECOND-SETTLEMENT",
            as_of=AS_OF,
            source="VALIDATION_ONLY:BROKER_EXCHANGE",
            positions=final_ledger.positions,
            complete=True,
            capability_verified=True,
            payload_sha256="b" * 64,
        ),
        snapshot_id="FRESH36-LEDGER-SECOND-SETTLEMENT-CONFLICT-REMAINS",
        as_of=AS_OF,
        ledger_snapshot_builder=builder,
    )
    assert final_decision.status is U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED
    assert final_decision.restore_allowed is False
    assert final_decision.pending_order_ids == (client_id,)
    assert final_decision.new_entry_enabled is False
    assert final_decision.order_submission_enabled is False

    latest_checkpoint = SqliteTrack2U19RecoveryStore(checkpoint_path).load_latest(group_id)
    assert latest_checkpoint["checkpoint_id"] == final_decision.checkpoint_id
    assert latest_checkpoint["status"] == U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED.value
    assert latest_checkpoint["new_entry_enabled"] is False
    assert latest_checkpoint["order_submission_enabled"] is False
    assert len(restarted_store.load_execution_journal_records()) == 3
    assert restarted_store.open_reconciliation_events(scope_key=client_id)[0]["status"] == "CONFLICT"


def test_fresh37_late_fill_conflict_candidates_are_preserved_and_individually_resolved_with_u19(
    tmp_path
):
    from environments.live.settlement.sqlite_settlement_store import encode_record

    store_path = tmp_path / "fresh37-settlement.sqlite3"
    checkpoint_path = tmp_path / "fresh37-u19.sqlite3"
    instrument_id = "SYNTHETIC_CONTRACT:FRESH37:OPTION:CALL"
    client_id = "FRESH37-CLIENT"
    broker_id = "FRESH37-BROKER"
    group_id = "SYNTHETIC:GROUP:FRESH37-CONFLICT-RESOLUTION"
    position = LivePositionAggregate(instrument_id)
    store = SQLiteSettlementStore(store_path)
    oms = _order_with_fill(
        store,
        client_id=client_id,
        broker_id=broker_id,
        instrument_id=instrument_id,
        side="BUY",
        leg_id="FRESH37-CALL",
        group_id=group_id,
        fills=(("SYNTHETIC:FRESH37:EXEC:ENTRY", 1, 0, "10.00"),),
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
        leg_id="FRESH37-CALL",
    ))
    bridge = LiveExecutionPositionBridge(
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(position),
        execution_event_deduplicator=ExecutionEventDeduplicator(
            persistence_store=store
        ),
        position_aggregate=position,
        settlement_store=store,
    )

    late_a = ExecutionReport(
        client_order_id=client_id,
        broker_order_id=broker_id,
        execution_id="SYNTHETIC:FRESH37:EXEC:LATE-A",
        status="PARTIALLY_FILLED",
        filled_quantity=1,
        remaining_quantity=1,
        execution_price=Decimal("10.20"),
        execution_timestamp=datetime(2026, 11, 18, 9, 40, tzinfo=timezone.utc),
        fee=Decimal("5"),
        group_id=group_id,
        leg_id="FRESH37-CALL",
    )
    conflict_a = replace(
        late_a, execution_price=Decimal("10.30"),
    )
    late_b = ExecutionReport(
        client_order_id=client_id,
        broker_order_id=broker_id,
        execution_id="SYNTHETIC:FRESH37:EXEC:LATE-B",
        status="FILLED",
        filled_quantity=1,
        remaining_quantity=0,
        execution_price=Decimal("10.25"),
        execution_timestamp=datetime(2026, 11, 18, 9, 41, tzinfo=timezone.utc),
        fee=Decimal("5"),
        group_id=group_id,
        leg_id="FRESH37-CALL",
    )
    conflict_b = replace(
        late_b, execution_price=Decimal("10.35"),
    )

    for report in (late_a, late_b):
        with pytest.raises(OrderStateTransitionError, match="RECONCILIATION_PENDING"):
            bridge.settle(report)
    for report in (conflict_a, conflict_b):
        with pytest.raises(
            SettlementStoreError,
            match="RECONCILIATION_INBOX_EXECUTION_ID_COLLISION",
        ):
            bridge.settle(report)

    history_a = store.late_fill_conflict_history(execution_id=late_a.execution_id)
    history_b = store.late_fill_conflict_history(execution_id=late_b.execution_id)
    assert len(history_a) == len(history_b) == 1
    detected_a = history_a[0]
    detected_b = history_b[0]
    assert detected_a["event_type"] == detected_b["event_type"] == "CONFLICT_DETECTED"
    assert detected_a["original_payload"]["execution_price"] == "10.20"
    assert detected_a["conflicting_payload"]["execution_price"] == "10.30"
    assert detected_b["original_payload"]["execution_price"] == "10.25"
    assert detected_b["conflicting_payload"]["execution_price"] == "10.35"
    assert detected_a["original_payload_sha256"] == hashlib.sha256(
        encode_record(detected_a["original_payload"]).encode("utf-8")
    ).hexdigest()
    assert detected_a["conflicting_payload_sha256"] == hashlib.sha256(
        encode_record(detected_a["conflicting_payload"]).encode("utf-8")
    ).hexdigest()

    with pytest.raises(
        SettlementStoreError, match="VALIDATION_ONLY_CONFLICT_EVIDENCE_REQUIRED"
    ):
        store.prepare_validation_only_late_fill_conflict_resolution(
            execution_id=late_a.execution_id,
            scope_key=client_id,
            original_payload_sha256=detected_a["original_payload_sha256"],
            conflicting_payload_sha256=detected_a["conflicting_payload_sha256"],
            selected_payload_sha256=detected_a["original_payload_sha256"],
            evidence_ref="TEST_ONLY:NOT_VALIDATION_NAMESPACE",
        )
    with pytest.raises(
        SettlementStoreError,
        match="LATE_FILL_CONFLICT_SELECTION_NOT_A_PRESERVED_CANDIDATE",
    ):
        store.prepare_validation_only_late_fill_conflict_resolution(
            execution_id=late_a.execution_id,
            scope_key=client_id,
            original_payload_sha256=detected_a["original_payload_sha256"],
            conflicting_payload_sha256=detected_a["conflicting_payload_sha256"],
            selected_payload_sha256="0" * 64,
            evidence_ref="VALIDATION_ONLY:FRESH37:INVALID_SELECTION",
        )
    with pytest.raises(
        SettlementStoreError, match="LATE_FILL_CONFLICT_EVENT_NOT_FOUND"
    ):
        store.prepare_validation_only_late_fill_conflict_resolution(
            execution_id=late_a.execution_id,
            scope_key="WRONG-ORDER-SCOPE",
            original_payload_sha256=detected_a["original_payload_sha256"],
            conflicting_payload_sha256=detected_a["conflicting_payload_sha256"],
            selected_payload_sha256=detected_a["original_payload_sha256"],
            evidence_ref="VALIDATION_ONLY:FRESH37:WRONG_SCOPE",
        )
    assert len(store.open_reconciliation_events(scope_key=client_id)) == 2
    assert position.qty == 1
    assert len(store.load_execution_journal_records()) == 1

    evidence_a = "VALIDATION_ONLY:FRESH37:SELECT-ORIGINAL-LATE-A"
    prepared_a = store.prepare_validation_only_late_fill_conflict_resolution(
        execution_id=late_a.execution_id,
        scope_key=client_id,
        original_payload_sha256=detected_a["original_payload_sha256"],
        conflicting_payload_sha256=detected_a["conflicting_payload_sha256"],
        selected_payload_sha256=detected_a["original_payload_sha256"],
        evidence_ref=evidence_a,
    )
    assert prepared_a is True
    assert store.prepare_validation_only_late_fill_conflict_resolution(
        execution_id=late_a.execution_id,
        scope_key=client_id,
        original_payload_sha256=detected_a["original_payload_sha256"],
        conflicting_payload_sha256=detected_a["conflicting_payload_sha256"],
        selected_payload_sha256=detected_a["original_payload_sha256"],
        evidence_ref=evidence_a,
    ) is False

    with pytest.raises(
        SettlementStoreError, match="LATE_FILL_CONFLICT_EVIDENCE_REF_MISMATCH"
    ):
        bridge.settle_authoritatively_reconciled_fill(
            late_a, authoritative_evidence_ref="VALIDATION_ONLY:FRESH37:WRONG_EVIDENCE"
        )
    with pytest.raises(OrderStateTransitionError, match="RECONCILIATION_PENDING"):
        bridge.settle(late_a)

    # The other event remains CONFLICT. The selected A report must match the
    # chosen original candidate; its competing payload is not accepted.
    with pytest.raises(
        SettlementStoreError,
        match="LATE_FILL_CONFLICT_BRIDGE_REPORT_PAYLOAD_MISMATCH",
    ):
        bridge.settle_authoritatively_reconciled_fill(
            conflict_a, authoritative_evidence_ref=evidence_a
        )
    assert len(store.load_execution_journal_records()) == 1
    assert position.qty == 1
    assert store.open_reconciliation_events(scope_key=client_id)[1]["status"] == "CONFLICT"

    settled_a = bridge.settle_authoritatively_reconciled_fill(
        late_a, authoritative_evidence_ref=evidence_a
    )
    assert settled_a.filled_quantity == 2
    assert position.qty == 2
    assert store.has_execution(late_a.execution_id)
    assert not store.has_execution(late_b.execution_id)
    assert [
        (item["execution_id"], item["status"])
        for item in store.open_reconciliation_events(scope_key=client_id)
    ] == [(late_b.execution_id, "CONFLICT")]
    assert store.unresolved_reconciliations()[0]["status"] == "CONFLICT"
    assert [item["event_type"] for item in store.late_fill_conflict_history(
        execution_id=late_a.execution_id
    )] == ["CONFLICT_DETECTED", "RESOLUTION_SELECTED", "SETTLED"]

    pending_builder = ValidationOnlyU19LedgerSnapshotBuilder(store)
    pending_ledger = pending_builder.build(
        group_id=group_id,
        snapshot_id="FRESH37-LEDGER-FIRST-CONFLICT-RESOLVED",
        as_of=AS_OF,
    )
    assert pending_ledger.positions == (U19Position(instrument_id, Decimal("2")),)
    assert pending_ledger.pending_order_ids == (client_id,)
    pending_coordinator = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(checkpoint_path),
        settlement_store=store,
    )
    pending_decision = pending_coordinator.recover_from_settlement_store(
        group_id=group_id,
        broker_snapshot=U19BrokerPositionSnapshot(
            group_id=group_id,
            snapshot_id="FRESH37-BROKER-ONE-CONFLICT-REMAINS",
            as_of=AS_OF,
            source="VALIDATION_ONLY:BROKER_EXCHANGE",
            positions=pending_ledger.positions,
            complete=True,
            capability_verified=True,
            payload_sha256="d" * 64,
        ),
        snapshot_id="FRESH37-LEDGER-FIRST-CONFLICT-RESOLVED",
        as_of=AS_OF,
        ledger_snapshot_builder=pending_builder,
    )
    assert pending_decision.status is U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED
    assert pending_decision.restore_allowed is False
    assert pending_decision.pending_order_ids == (client_id,)
    assert pending_decision.new_entry_enabled is False
    assert pending_decision.order_submission_enabled is False

    # Restart between the two conflict resolutions. The second event selects
    # the competing candidate, proving either preserved candidate can be chosen.
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
    assert restarted_oms.get(client_id).filled_quantity == 2
    assert restarted_position.qty == 2

    evidence_b = "VALIDATION_ONLY:FRESH37:SELECT-CONFLICTING-LATE-B"
    assert restarted_store.prepare_validation_only_late_fill_conflict_resolution(
        execution_id=late_b.execution_id,
        scope_key=client_id,
        original_payload_sha256=detected_b["original_payload_sha256"],
        conflicting_payload_sha256=detected_b["conflicting_payload_sha256"],
        selected_payload_sha256=detected_b["conflicting_payload_sha256"],
        evidence_ref=evidence_b,
    ) is True

    with pytest.raises(
        SettlementStoreError,
        match="LATE_FILL_CONFLICT_BRIDGE_REPORT_PAYLOAD_MISMATCH",
    ):
        restarted_bridge.settle_authoritatively_reconciled_fill(
            late_b, authoritative_evidence_ref=evidence_b
        )
    assert restarted_position.qty == 2
    assert len(restarted_store.load_execution_journal_records()) == 2

    settled_b = restarted_bridge.settle_authoritatively_reconciled_fill(
        conflict_b, authoritative_evidence_ref=evidence_b
    )
    assert settled_b.filled_quantity == 3
    assert restarted_position.qty == 3
    assert restarted_store.pending_reconciliation_events(scope_key=client_id) == ()
    assert restarted_store.open_reconciliation_events(scope_key=client_id) == ()
    assert restarted_store.unresolved_reconciliations() == ()
    assert restarted_store.load_position_state(instrument_id)["qty"] == 3
    assert len(restarted_store.load_execution_journal_records()) == 3
    assert [item["event_type"] for item in restarted_store.late_fill_conflict_history(
        execution_id=late_b.execution_id
    )] == ["CONFLICT_DETECTED", "RESOLUTION_SELECTED", "SETTLED"]

    # Conflict audit is append-only and each execution has its own resolution.
    with sqlite3.connect(store_path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="RECONCILIATION_CONFLICT_EVENTS_APPEND_ONLY"):
            connection.execute(
                "UPDATE reconciliation_conflict_events SET evidence_ref='tampered' WHERE execution_id=?",
                (late_a.execution_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="RECONCILIATION_CONFLICT_EVENTS_APPEND_ONLY"):
            connection.execute(
                "DELETE FROM reconciliation_conflict_events WHERE execution_id=?",
                (late_a.execution_id,),
            )

    final_store = SQLiteSettlementStore(store_path)
    builder = ValidationOnlyU19LedgerSnapshotBuilder(final_store)
    ledger = builder.build(
        group_id=group_id,
        snapshot_id="FRESH37-LEDGER-ALL-CONFLICTS-RESOLVED",
        as_of=AS_OF,
    )
    assert ledger.positions == (U19Position(instrument_id, Decimal("3")),)
    assert ledger.pending_order_ids == ()
    coordinator = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(checkpoint_path),
        settlement_store=final_store,
    )
    decision = coordinator.recover_from_settlement_store(
        group_id=group_id,
        broker_snapshot=U19BrokerPositionSnapshot(
            group_id=group_id,
            snapshot_id="FRESH37-BROKER-VALIDATION-PROXY",
            as_of=AS_OF,
            source="VALIDATION_ONLY:BROKER_EXCHANGE",
            positions=ledger.positions,
            complete=True,
            capability_verified=True,
            payload_sha256="c" * 64,
        ),
        snapshot_id="FRESH37-LEDGER-ALL-CONFLICTS-RESOLVED",
        as_of=AS_OF,
        ledger_snapshot_builder=builder,
    )
    assert decision.status is U19RecoveryStatus.RESTORE_ALLOWED
    assert decision.positions == ledger.positions
    assert decision.pending_order_ids == ()
    assert decision.new_entry_enabled is False
    assert decision.order_submission_enabled is False
    assert SqliteTrack2U19RecoveryStore(checkpoint_path).load_latest(group_id)[
        "status"
    ] == U19RecoveryStatus.RESTORE_ALLOWED.value


def test_fresh37_conflict_selection_cannot_clear_unrelated_scope_conflict(tmp_path):
    from environments.live.settlement.sqlite_settlement_store import encode_record

    store_path = tmp_path / "fresh37-unrelated-conflict.sqlite3"
    instrument_id = "SYNTHETIC_CONTRACT:FRESH37:OPTION:PUT"
    client_id = "FRESH37-UNRELATED-CLIENT"
    broker_id = "FRESH37-UNRELATED-BROKER"
    group_id = "SYNTHETIC:GROUP:FRESH37-UNRELATED-CONFLICT"
    position = LivePositionAggregate(instrument_id)
    store = SQLiteSettlementStore(store_path)
    oms = _order_with_fill(
        store,
        client_id=client_id,
        broker_id=broker_id,
        instrument_id=instrument_id,
        side="BUY",
        leg_id="FRESH37-PUT",
        group_id=group_id,
        fills=(("SYNTHETIC:FRESH37:EXEC:UNRELATED-ENTRY", 1, 0, "8.00"),),
        order_quantity=2,
        position_aggregate=position,
    )
    oms.apply_cancel(ExecutionReport(
        client_order_id=client_id,
        broker_order_id=broker_id,
        execution_id=None,
        status="CANCELLED",
        filled_quantity=0,
        remaining_quantity=1,
        execution_price=None,
        execution_timestamp=datetime(2026, 11, 18, 9, 35, tzinfo=timezone.utc),
        group_id=group_id,
        leg_id="FRESH37-PUT",
    ))
    bridge = LiveExecutionPositionBridge(
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(position),
        execution_event_deduplicator=ExecutionEventDeduplicator(
            persistence_store=store
        ),
        position_aggregate=position,
        settlement_store=store,
    )
    late_fill = ExecutionReport(
        client_order_id=client_id,
        broker_order_id=broker_id,
        execution_id="SYNTHETIC:FRESH37:EXEC:UNRELATED-LATE",
        status="FILLED",
        filled_quantity=1,
        remaining_quantity=0,
        execution_price=Decimal("8.10"),
        execution_timestamp=datetime(2026, 11, 18, 9, 40, tzinfo=timezone.utc),
        fee=Decimal("5"),
        group_id=group_id,
        leg_id="FRESH37-PUT",
    )
    conflicting_fill = replace(
        late_fill, execution_price=Decimal("8.20"),
    )
    with pytest.raises(OrderStateTransitionError, match="RECONCILIATION_PENDING"):
        bridge.settle(late_fill)
    with pytest.raises(SettlementStoreError, match="RECONCILIATION_INBOX_EXECUTION_ID_COLLISION"):
        bridge.settle(conflicting_fill)
    detected = store.late_fill_conflict_history(
        execution_id=late_fill.execution_id
    )[0]

    # Simulate an unrelated reconciliation conflict sharing the same scope.
    with sqlite3.connect(store_path) as connection:
        connection.execute(
            """UPDATE reconciliation_state
               SET reason='UNRELATED_MANUAL_RECONCILIATION_CONFLICT',
                   payload_json=?
               WHERE scope_key=?""",
            (
                encode_record({"execution_id": "UNRELATED-OTHER-EVENT"}),
                client_id,
            ),
        )

    with pytest.raises(
        SettlementStoreError,
        match="LATE_FILL_CONFLICT_CANNOT_CLEAR_UNRELATED_SCOPE_CONFLICT",
    ):
        store.prepare_validation_only_late_fill_conflict_resolution(
            execution_id=late_fill.execution_id,
            scope_key=client_id,
            original_payload_sha256=detected["original_payload_sha256"],
            conflicting_payload_sha256=detected["conflicting_payload_sha256"],
            selected_payload_sha256=detected["original_payload_sha256"],
            evidence_ref="VALIDATION_ONLY:FRESH37:UNRELATED_CONFLICT_GUARD",
        )
    inbox = store.open_reconciliation_events(scope_key=client_id)
    assert len(inbox) == 1
    assert inbox[0]["status"] == "CONFLICT"
    assert [item["event_type"] for item in store.late_fill_conflict_history(
        execution_id=late_fill.execution_id
    )] == ["CONFLICT_DETECTED"]
    assert store.unresolved_reconciliations()[0]["reason"] == (
        "UNRELATED_MANUAL_RECONCILIATION_CONFLICT"
    )
    assert len(store.load_execution_journal_records()) == 1
    assert position.qty == 1


def test_fresh38_journal_collision_preserves_both_payloads_and_confirms_original_without_reapplying_fill(
    tmp_path
):
    from environments.live.settlement.sqlite_settlement_store import encode_record

    store_path = tmp_path / "fresh38-settlement.sqlite3"
    checkpoint_path = tmp_path / "fresh38-u19.sqlite3"
    instrument_id = "SYNTHETIC_CONTRACT:FRESH38:OPTION:CALL"
    client_id = "FRESH38-CLIENT"
    broker_id = "FRESH38-BROKER"
    group_id = "SYNTHETIC:GROUP:FRESH38-JOURNAL-COLLISION"
    position = LivePositionAggregate(instrument_id)
    store = SQLiteSettlementStore(store_path)
    oms = _order_with_fill(
        store,
        client_id=client_id,
        broker_id=broker_id,
        instrument_id=instrument_id,
        side="BUY",
        leg_id="FRESH38-CALL",
        group_id=group_id,
        fills=(("SYNTHETIC:FRESH38:EXEC:ALREADY-SETTLED", 1, 0, "10.00"),),
        order_quantity=2,
        position_aggregate=position,
    )
    bridge = LiveExecutionPositionBridge(
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(position),
        execution_event_deduplicator=ExecutionEventDeduplicator(
            persistence_store=store
        ),
        position_aggregate=position,
        settlement_store=store,
    )
    original_report = ExecutionReport(
        client_order_id=client_id,
        broker_order_id=broker_id,
        execution_id="SYNTHETIC:FRESH38:EXEC:ALREADY-SETTLED",
        status="PARTIALLY_FILLED",
        filled_quantity=1,
        remaining_quantity=1,
        execution_price=Decimal("10.00"),
        execution_timestamp=datetime(2026, 11, 18, 9, 30, tzinfo=timezone.utc),
        fee=Decimal("5"),
        group_id=group_id,
        leg_id="FRESH38-CALL",
    )
    conflicting_report = replace(
        original_report, execution_price=Decimal("10.50"),
    )

    before_journal = store.load_execution_journal_records()
    before_position = position.snapshot()
    before_oms = oms.get(client_id)
    assert len(before_journal) == 1
    assert position.qty == 1
    with pytest.raises(SettlementStoreError, match="EXECUTION_ID_COLLISION"):
        bridge.settle(conflicting_report)

    history = store.execution_journal_conflict_history(
        execution_id=original_report.execution_id
    )
    assert len(history) == 1
    detected = history[0]
    assert detected["event_type"] == "CONFLICT_DETECTED"
    assert detected["original_client_order_id"] == client_id
    assert detected["incoming_client_order_id"] == client_id
    assert detected["original_payload"]["execution_price"] == "10.00"
    assert detected["incoming_payload"]["execution_price"] == "10.50"
    assert detected["original_payload_sha256"] == __import__("hashlib").sha256(
        encode_record(detected["original_payload"]).encode("utf-8")
    ).hexdigest()
    assert detected["incoming_payload_sha256"] == __import__("hashlib").sha256(
        encode_record(detected["incoming_payload"]).encode("utf-8")
    ).hexdigest()
    assert store.load_execution_journal_records() == before_journal
    assert position.snapshot() == before_position
    assert oms.get(client_id) == before_oms

    builder = ValidationOnlyU19LedgerSnapshotBuilder(store)
    pending_ledger = builder.build(
        group_id=group_id,
        snapshot_id="FRESH38-LEDGER-JOURNAL-CONFLICT",
        as_of=AS_OF,
    )
    assert pending_ledger.positions == (U19Position(instrument_id, Decimal("1")),)
    assert pending_ledger.pending_order_ids == (client_id,)
    coordinator = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(checkpoint_path),
        settlement_store=store,
    )
    pending_decision = coordinator.recover_from_settlement_store(
        group_id=group_id,
        broker_snapshot=U19BrokerPositionSnapshot(
            group_id=group_id,
            snapshot_id="FRESH38-BROKER-PROXY-PENDING",
            as_of=AS_OF,
            source="VALIDATION_ONLY:BROKER_EXCHANGE",
            positions=pending_ledger.positions,
            complete=True,
            capability_verified=True,
            payload_sha256="a" * 64,
        ),
        snapshot_id="FRESH38-LEDGER-JOURNAL-CONFLICT",
        as_of=AS_OF,
        ledger_snapshot_builder=builder,
    )
    assert pending_decision.status is U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED
    assert pending_decision.restore_allowed is False
    assert pending_decision.new_entry_enabled is False
    assert pending_decision.order_submission_enabled is False

    with pytest.raises(
        SettlementStoreError,
        match="EXECUTION_JOURNAL_CONFLICT_INCOMING_CANDIDATE_REQUIRES_POSITION_ADJUSTMENT_REVIEW",
    ):
        store.prepare_validation_only_execution_journal_conflict_resolution(
            execution_id=original_report.execution_id,
            scope_key=client_id,
            original_payload_sha256=detected["original_payload_sha256"],
            incoming_payload_sha256=detected["incoming_payload_sha256"],
            selected_payload_sha256=detected["incoming_payload_sha256"],
            evidence_ref="VALIDATION_ONLY:FRESH38:SELECT-INCOMING",
        )
    with pytest.raises(
        SettlementStoreError,
        match="VALIDATION_ONLY_JOURNAL_CONFLICT_EVIDENCE_REQUIRED",
    ):
        store.prepare_validation_only_execution_journal_conflict_resolution(
            execution_id=original_report.execution_id,
            scope_key=client_id,
            original_payload_sha256=detected["original_payload_sha256"],
            incoming_payload_sha256=detected["incoming_payload_sha256"],
            selected_payload_sha256=detected["original_payload_sha256"],
            evidence_ref="BROKER:NOT-VALIDATION-ONLY",
        )

    assert store.prepare_validation_only_execution_journal_conflict_resolution(
        execution_id=original_report.execution_id,
        scope_key=client_id,
        original_payload_sha256=detected["original_payload_sha256"],
        incoming_payload_sha256=detected["incoming_payload_sha256"],
        selected_payload_sha256=detected["original_payload_sha256"],
        evidence_ref="VALIDATION_ONLY:FRESH38:CONFIRM-ORIGINAL-JOURNAL",
    ) is True
    assert store.prepare_validation_only_execution_journal_conflict_resolution(
        execution_id=original_report.execution_id,
        scope_key=client_id,
        original_payload_sha256=detected["original_payload_sha256"],
        incoming_payload_sha256=detected["incoming_payload_sha256"],
        selected_payload_sha256=detected["original_payload_sha256"],
        evidence_ref="VALIDATION_ONLY:FRESH38:CONFIRM-ORIGINAL-JOURNAL",
    ) is False

    # Confirmation does not replay or rewrite the already-settled fill.
    assert store.load_execution_journal_records() == before_journal
    assert store.load_position_state(instrument_id)["qty"] == 1
    assert position.snapshot() == before_position
    assert oms.get(client_id).filled_quantity == 1
    assert store.unresolved_reconciliations() == ()
    assert [
        item["event_type"]
        for item in store.execution_journal_conflict_history(
            execution_id=original_report.execution_id
        )
    ] == ["CONFLICT_DETECTED", "ORIGINAL_CONFIRMED"]

    # The original replay remains idempotent; a repeat of the already-adjudicated
    # conflicting payload is rejected without reopening the resolved gate.
    assert bridge.settle(original_report).filled_quantity == 1
    with pytest.raises(SettlementStoreError, match="EXECUTION_ID_COLLISION"):
        bridge.settle(conflicting_report)
    assert store.unresolved_reconciliations() == ()
    assert store.load_execution_journal_records() == before_journal
    assert position.snapshot() == before_position

    final_ledger = builder.build(
        group_id=group_id,
        snapshot_id="FRESH38-LEDGER-ORIGINAL-CONFIRMED",
        as_of=AS_OF,
    )
    assert final_ledger.positions == (U19Position(instrument_id, Decimal("1")),)
    assert final_ledger.pending_order_ids == ()
    final_decision = coordinator.recover_from_settlement_store(
        group_id=group_id,
        broker_snapshot=U19BrokerPositionSnapshot(
            group_id=group_id,
            snapshot_id="FRESH38-BROKER-PROXY-ORIGINAL-CONFIRMED",
            as_of=AS_OF,
            source="VALIDATION_ONLY:BROKER_EXCHANGE",
            positions=final_ledger.positions,
            complete=True,
            capability_verified=True,
            payload_sha256="b" * 64,
        ),
        snapshot_id="FRESH38-LEDGER-ORIGINAL-CONFIRMED",
        as_of=AS_OF,
        ledger_snapshot_builder=builder,
    )
    assert final_decision.status is U19RecoveryStatus.RESTORE_ALLOWED
    assert final_decision.positions == final_ledger.positions
    assert final_decision.new_entry_enabled is False
    assert final_decision.order_submission_enabled is False

    with sqlite3.connect(store_path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="EXECUTION_JOURNAL_CONFLICT_EVENTS_APPEND_ONLY"):
            connection.execute(
                "UPDATE execution_journal_conflict_events SET evidence_ref='tampered' WHERE execution_id=?",
                (original_report.execution_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="EXECUTION_JOURNAL_CONFLICT_EVENTS_APPEND_ONLY"):
            connection.execute(
                "DELETE FROM execution_journal_conflict_events WHERE execution_id=?",
                (original_report.execution_id,),
            )


def test_fresh39_cross_order_execution_id_collision_sets_global_u19_gate_for_both_groups(
    tmp_path
):
    store_path = tmp_path / "fresh39-settlement.sqlite3"
    checkpoint_path = tmp_path / "fresh39-u19.sqlite3"
    shared_execution_id = "SYNTHETIC:FRESH39:EXEC:SHARED-ID"
    original_instrument = "SYNTHETIC_CONTRACT:FRESH39:GROUP-A:CALL"
    incoming_instrument = "SYNTHETIC_CONTRACT:FRESH39:GROUP-B:PUT"
    original_client = "FRESH39-CLIENT-A"
    incoming_client = "FRESH39-CLIENT-B"
    original_broker = "FRESH39-BROKER-A"
    incoming_broker = "FRESH39-BROKER-B"
    original_group = "SYNTHETIC:GROUP:FRESH39-A"
    incoming_group = "SYNTHETIC:GROUP:FRESH39-B"
    store = SQLiteSettlementStore(store_path)

    original_position = LivePositionAggregate(original_instrument)
    original_oms = _order_with_fill(
        store,
        client_id=original_client,
        broker_id=original_broker,
        instrument_id=original_instrument,
        side="BUY",
        leg_id="FRESH39-A-CALL",
        group_id=original_group,
        fills=((shared_execution_id, 1, 0, "11.00"),),
        order_quantity=2,
        position_aggregate=original_position,
    )

    incoming_position = LivePositionAggregate(incoming_instrument)
    incoming_oms = _order_with_fill(
        store,
        client_id=incoming_client,
        broker_id=incoming_broker,
        instrument_id=incoming_instrument,
        side="BUY",
        leg_id="FRESH39-B-PUT",
        group_id=incoming_group,
        fills=(),
        order_quantity=1,
        position_aggregate=incoming_position,
    )
    incoming_bridge = LiveExecutionPositionBridge(
        order_state_machine=incoming_oms,
        position_fill_adapter=LivePositionFillAdapter(incoming_position),
        execution_event_deduplicator=ExecutionEventDeduplicator(
            persistence_store=store
        ),
        position_aggregate=incoming_position,
        settlement_store=store,
    )
    incoming_report = ExecutionReport(
        client_order_id=incoming_client,
        broker_order_id=incoming_broker,
        execution_id=shared_execution_id,
        status="FILLED",
        filled_quantity=1,
        remaining_quantity=0,
        execution_price=Decimal("22.00"),
        execution_timestamp=datetime(2026, 11, 18, 9, 45, tzinfo=timezone.utc),
        fee=Decimal("5"),
        group_id=incoming_group,
        leg_id="FRESH39-B-PUT",
    )

    with pytest.raises(SettlementStoreError, match="EXECUTION_ID_COLLISION"):
        incoming_bridge.settle(incoming_report)

    history = store.execution_journal_conflict_history(
        execution_id=shared_execution_id
    )
    assert len(history) == 1
    detected = history[0]
    assert detected["event_type"] == "CONFLICT_DETECTED"
    assert detected["scope_key"] == "__runtime_bootstrap__"
    assert detected["original_client_order_id"] == original_client
    assert detected["incoming_client_order_id"] == incoming_client
    assert detected["original_payload"]["group_id"] == original_group
    assert detected["incoming_payload"]["group_id"] == incoming_group
    assert store.has_execution(shared_execution_id)
    assert len(store.load_execution_journal_records()) == 1
    assert original_position.qty == 1
    assert incoming_position.qty == 0
    assert store.unresolved_reconciliations()[0]["scope_key"] == "__runtime_bootstrap__"

    original_builder = ValidationOnlyU19LedgerSnapshotBuilder(store)
    original_ledger = original_builder.build(
        group_id=original_group,
        snapshot_id="FRESH39-LEDGER-GROUP-A",
        as_of=AS_OF,
    )
    incoming_builder = ValidationOnlyU19LedgerSnapshotBuilder(store)
    incoming_ledger = incoming_builder.build(
        group_id=incoming_group,
        snapshot_id="FRESH39-LEDGER-GROUP-B",
        as_of=AS_OF,
    )
    assert original_ledger.positions == (U19Position(original_instrument, Decimal("1")),)
    assert incoming_ledger.positions == ()
    assert original_ledger.pending_order_ids == ("__GLOBAL_RECONCILIATION__",)
    assert incoming_ledger.pending_order_ids == ("__GLOBAL_RECONCILIATION__",)

    coordinator = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(checkpoint_path),
        settlement_store=store,
    )
    for group_id, ledger, snapshot_id in (
        (original_group, original_ledger, "FRESH39-BROKER-GROUP-A"),
        (incoming_group, incoming_ledger, "FRESH39-BROKER-GROUP-B"),
    ):
        decision = coordinator.recover_from_settlement_store(
            group_id=group_id,
            broker_snapshot=U19BrokerPositionSnapshot(
                group_id=group_id,
                snapshot_id=snapshot_id,
                as_of=AS_OF,
                source="VALIDATION_ONLY:BROKER_EXCHANGE",
                positions=ledger.positions,
                complete=True,
                capability_verified=True,
                payload_sha256=("a" if group_id == original_group else "b") * 64,
            ),
            snapshot_id=f"{snapshot_id}-LEDGER",
            as_of=AS_OF,
            ledger_snapshot_builder=(
                original_builder if group_id == original_group else incoming_builder
            ),
        )
        assert decision.status is U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED
        assert decision.restore_allowed is False
        assert decision.pending_order_ids == ("__GLOBAL_RECONCILIATION__",)
        assert decision.new_entry_enabled is False
        assert decision.order_submission_enabled is False

    with pytest.raises(
        SettlementStoreError,
        match="EXECUTION_JOURNAL_CONFLICT_ORDER_IDENTITY_MISMATCH_REQUIRES_MANUAL_REVIEW",
    ):
        store.prepare_validation_only_execution_journal_conflict_resolution(
            execution_id=shared_execution_id,
            scope_key="__runtime_bootstrap__",
            original_payload_sha256=detected["original_payload_sha256"],
            incoming_payload_sha256=detected["incoming_payload_sha256"],
            selected_payload_sha256=detected["original_payload_sha256"],
            evidence_ref="VALIDATION_ONLY:FRESH39:CROSS_ORDER_NOT_RESOLVABLE",
        )

    assert store.unresolved_reconciliations()[0]["status"] == "CONFLICT"
    assert [
        item["event_type"]
        for item in store.execution_journal_conflict_history(
            execution_id=shared_execution_id
        )
    ] == ["CONFLICT_DETECTED"]
    assert len(store.load_execution_journal_records()) == 1
    assert original_position.qty == 1
    assert incoming_position.qty == 0


def test_fresh40_multiple_global_collisions_and_order_local_conflict_keep_all_u19_groups_gated(
    tmp_path
):
    store_path = tmp_path / "fresh40-settlement.sqlite3"
    checkpoint_path = tmp_path / "fresh40-u19.sqlite3"
    store = SQLiteSettlementStore(store_path)

    def make_group(client, broker, instrument, group, leg, execution_id, price, quantity=2, fills=None):
        position = LivePositionAggregate(instrument)
        oms = _order_with_fill(
            store,
            client_id=client,
            broker_id=broker,
            instrument_id=instrument,
            side="BUY",
            leg_id=leg,
            group_id=group,
            fills=(
                fills
                if fills is not None
                else ((execution_id, 1, 0, price),)
            ),
            order_quantity=quantity,
            position_aggregate=position,
        )
        bridge = LiveExecutionPositionBridge(
            order_state_machine=oms,
            position_fill_adapter=LivePositionFillAdapter(position),
            execution_event_deduplicator=ExecutionEventDeduplicator(
                persistence_store=store
            ),
            position_aggregate=position,
            settlement_store=store,
        )
        return oms, position, bridge

    # Two separate cross-order journal collisions share one global gate.
    oms_a, pos_a, bridge_a = make_group(
        "FRESH40-A-CLIENT", "FRESH40-A-BROKER",
        "SYNTHETIC_CONTRACT:FRESH40:A", "SYNTHETIC:GROUP:FRESH40-A",
        "FRESH40-A-LEG", "SYNTHETIC:FRESH40:EXEC:GLOBAL-1", "10.00",
    )
    oms_b, pos_b, bridge_b = make_group(
        "FRESH40-B-CLIENT", "FRESH40-B-BROKER",
        "SYNTHETIC_CONTRACT:FRESH40:B", "SYNTHETIC:GROUP:FRESH40-B",
        "FRESH40-B-LEG", "SYNTHETIC:FRESH40:EXEC:GLOBAL-1", "20.00",
        quantity=1, fills=(),
    )
    oms_c, pos_c, bridge_c = make_group(
        "FRESH40-C-CLIENT", "FRESH40-C-BROKER",
        "SYNTHETIC_CONTRACT:FRESH40:C", "SYNTHETIC:GROUP:FRESH40-C",
        "FRESH40-C-LEG", "SYNTHETIC:FRESH40:EXEC:GLOBAL-2", "30.00",
    )
    oms_d, pos_d, bridge_d = make_group(
        "FRESH40-D-CLIENT", "FRESH40-D-BROKER",
        "SYNTHETIC_CONTRACT:FRESH40:D", "SYNTHETIC:GROUP:FRESH40-D",
        "FRESH40-D-LEG", "SYNTHETIC:FRESH40:EXEC:GLOBAL-2", "40.00",
        quantity=1, fills=(),
    )
    for bridge, client, broker, group, leg, execution_id, price in (
        (bridge_b, "FRESH40-B-CLIENT", "FRESH40-B-BROKER", "SYNTHETIC:GROUP:FRESH40-B", "FRESH40-B-LEG", "SYNTHETIC:FRESH40:EXEC:GLOBAL-1", "20.00"),
        (bridge_d, "FRESH40-D-CLIENT", "FRESH40-D-BROKER", "SYNTHETIC:GROUP:FRESH40-D", "FRESH40-D-LEG", "SYNTHETIC:FRESH40:EXEC:GLOBAL-2", "40.00"),
    ):
        incoming = ExecutionReport(
            client_order_id=client,
            broker_order_id=broker,
            execution_id=execution_id,
            status="FILLED",
            filled_quantity=1,
            remaining_quantity=0,
            execution_price=Decimal(price),
            execution_timestamp=datetime(2026, 11, 18, 9, 45, tzinfo=timezone.utc),
            fee=Decimal("5"),
            group_id=group,
            leg_id=leg,
        )
        with pytest.raises(SettlementStoreError, match="EXECUTION_ID_COLLISION"):
            bridge.settle(incoming)

    global_history = store.execution_journal_conflict_history(
        scope_key="__runtime_bootstrap__"
    )
    assert len(global_history) == 2
    assert {item["execution_id"] for item in global_history} == {
        "SYNTHETIC:FRESH40:EXEC:GLOBAL-1",
        "SYNTHETIC:FRESH40:EXEC:GLOBAL-2",
    }

    # A separate order-local late-fill conflict is resolved individually.
    oms_e, pos_e, bridge_e = make_group(
        "FRESH40-E-CLIENT", "FRESH40-E-BROKER",
        "SYNTHETIC_CONTRACT:FRESH40:E", "SYNTHETIC:GROUP:FRESH40-E",
        "FRESH40-E-LEG", "SYNTHETIC:FRESH40:EXEC:E-ENTRY", "9.00",
    )
    oms_e.apply_cancel(ExecutionReport(
        client_order_id="FRESH40-E-CLIENT",
        broker_order_id="FRESH40-E-BROKER",
        execution_id=None,
        status="CANCELLED",
        filled_quantity=0,
        remaining_quantity=1,
        execution_price=None,
        execution_timestamp=datetime(2026, 11, 18, 9, 35, tzinfo=timezone.utc),
        group_id="SYNTHETIC:GROUP:FRESH40-E",
        leg_id="FRESH40-E-LEG",
    ))
    late_e = ExecutionReport(
        client_order_id="FRESH40-E-CLIENT",
        broker_order_id="FRESH40-E-BROKER",
        execution_id="SYNTHETIC:FRESH40:EXEC:E-LATE",
        status="FILLED",
        filled_quantity=1,
        remaining_quantity=0,
        execution_price=Decimal("9.10"),
        execution_timestamp=datetime(2026, 11, 18, 9, 40, tzinfo=timezone.utc),
        fee=Decimal("5"),
        group_id="SYNTHETIC:GROUP:FRESH40-E",
        leg_id="FRESH40-E-LEG",
    )
    conflicting_e = replace(late_e, execution_price=Decimal("9.20"))
    with pytest.raises(OrderStateTransitionError, match="RECONCILIATION_PENDING"):
        bridge_e.settle(late_e)
    with pytest.raises(
        SettlementStoreError,
        match="RECONCILIATION_INBOX_EXECUTION_ID_COLLISION",
    ):
        bridge_e.settle(conflicting_e)
    local_history = store.late_fill_conflict_history(
        execution_id=late_e.execution_id
    )[0]
    evidence_e = "VALIDATION_ONLY:FRESH40:RESOLVE-ORDER-LOCAL-E"
    assert store.prepare_validation_only_late_fill_conflict_resolution(
        execution_id=late_e.execution_id,
        scope_key="FRESH40-E-CLIENT",
        original_payload_sha256=local_history["original_payload_sha256"],
        conflicting_payload_sha256=local_history["conflicting_payload_sha256"],
        selected_payload_sha256=local_history["original_payload_sha256"],
        evidence_ref=evidence_e,
    ) is True
    bridge_e.settle_authoritatively_reconciled_fill(
        late_e, authoritative_evidence_ref=evidence_e
    )
    assert pos_e.qty == 2
    assert store.pending_reconciliation_events(scope_key="FRESH40-E-CLIENT") == ()
    assert store.unresolved_reconciliations() == (
        store.unresolved_reconciliations()[0],
    )
    assert store.unresolved_reconciliations()[0]["scope_key"] == "__runtime_bootstrap__"
    assert store.unresolved_reconciliations()[0]["status"] == "CONFLICT"

    groups = (
        ("SYNTHETIC:GROUP:FRESH40-A", pos_a, "FRESH40-A"),
        ("SYNTHETIC:GROUP:FRESH40-B", pos_b, "FRESH40-B"),
        ("SYNTHETIC:GROUP:FRESH40-C", pos_c, "FRESH40-C"),
        ("SYNTHETIC:GROUP:FRESH40-D", pos_d, "FRESH40-D"),
        ("SYNTHETIC:GROUP:FRESH40-E", pos_e, "FRESH40-E"),
    )
    builders = {}
    coordinator = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(checkpoint_path),
        settlement_store=store,
    )
    for group_id, position, suffix in groups:
        builder = ValidationOnlyU19LedgerSnapshotBuilder(store)
        builders[group_id] = builder
        ledger = builder.build(
            group_id=group_id,
            snapshot_id=f"{suffix}-LEDGER-GLOBAL-GATE",
            as_of=AS_OF,
        )
        assert ledger.pending_order_ids == ("__GLOBAL_RECONCILIATION__",)
        expected_position = (
            U19Position(position.instrument_id, Decimal(str(position.qty)))
            if position.qty
            else None
        )
        assert ledger.positions == ((expected_position,) if expected_position else ())
        decision = coordinator.recover_from_settlement_store(
            group_id=group_id,
            broker_snapshot=U19BrokerPositionSnapshot(
                group_id=group_id,
                snapshot_id=f"{suffix}-BROKER-PROXY",
                as_of=AS_OF,
                source="VALIDATION_ONLY:BROKER_EXCHANGE",
                positions=ledger.positions,
                complete=True,
                capability_verified=True,
                payload_sha256=("a" if suffix in {"FRESH40-A", "FRESH40-B"} else "b") * 64,
            ),
            snapshot_id=f"{suffix}-LEDGER-GLOBAL-GATE",
            as_of=AS_OF,
            ledger_snapshot_builder=builder,
        )
        assert decision.status is U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED
        assert decision.restore_allowed is False
        assert decision.pending_order_ids == ("__GLOBAL_RECONCILIATION__",)
        assert decision.new_entry_enabled is False
        assert decision.order_submission_enabled is False

    # Resolving one global collision is prohibited by cross-order identity mismatch;
    # the other global collision and all group checkpoints remain gated.
    first_global = global_history[0]
    with pytest.raises(
        SettlementStoreError,
        match="EXECUTION_JOURNAL_CONFLICT_ORDER_IDENTITY_MISMATCH_REQUIRES_MANUAL_REVIEW",
    ):
        store.prepare_validation_only_execution_journal_conflict_resolution(
            execution_id=first_global["execution_id"],
            scope_key="__runtime_bootstrap__",
            original_payload_sha256=first_global["original_payload_sha256"],
            incoming_payload_sha256=first_global["incoming_payload_sha256"],
            selected_payload_sha256=first_global["original_payload_sha256"],
            evidence_ref="VALIDATION_ONLY:FRESH40:GLOBAL-COLLISION-RESOLUTION",
        )
    assert len(store.execution_journal_conflict_history(
        scope_key="__runtime_bootstrap__"
    )) == 2
    assert store.unresolved_reconciliations()[0]["scope_key"] == "__runtime_bootstrap__"
    for group_id, builder in builders.items():
        ledger = builder.build(
            group_id=group_id,
            snapshot_id=f"{group_id}-RECHECK",
            as_of=AS_OF,
        )
        assert ledger.pending_order_ids == ("__GLOBAL_RECONCILIATION__",)

    # FRESH-41: reopen both SQLite stores after partial adjudication attempts.
    # Cross-order journal collisions are intentionally not resolvable by the
    # same-order validation-only confirmer; the global gate must survive restart.
    journal_count_before_restart = len(store.load_execution_journal_records())
    for conflict in global_history:
        with pytest.raises(
            SettlementStoreError,
            match="EXECUTION_JOURNAL_CONFLICT_ORDER_IDENTITY_MISMATCH_REQUIRES_MANUAL_REVIEW",
        ):
            store.prepare_validation_only_execution_journal_conflict_resolution(
                execution_id=conflict["execution_id"],
                scope_key="__runtime_bootstrap__",
                original_payload_sha256=conflict["original_payload_sha256"],
                incoming_payload_sha256=conflict["incoming_payload_sha256"],
                selected_payload_sha256=conflict["original_payload_sha256"],
                evidence_ref=f"VALIDATION_ONLY:FRESH41:{conflict['execution_id']}:PARTIAL",
            )

    restarted_store = SQLiteSettlementStore(store_path)
    restarted_history = restarted_store.execution_journal_conflict_history(
        scope_key="__runtime_bootstrap__"
    )
    assert len(restarted_history) == 2
    assert {item["event_type"] for item in restarted_history} == {"CONFLICT_DETECTED"}
    assert len(restarted_store.load_execution_journal_records()) == journal_count_before_restart
    assert len(restarted_store.unresolved_reconciliations()) == 1
    assert restarted_store.unresolved_reconciliations()[0]["scope_key"] == "__runtime_bootstrap__"
    assert restarted_store.unresolved_reconciliations()[0]["status"] == "CONFLICT"
    assert restarted_store.pending_reconciliation_events(scope_key="FRESH40-E-CLIENT") == ()

    restarted_coordinator = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(checkpoint_path),
        settlement_store=restarted_store,
    )
    for group_id, position, suffix in groups:
        builder = ValidationOnlyU19LedgerSnapshotBuilder(restarted_store)
        ledger = builder.build(
            group_id=group_id,
            snapshot_id=f"{suffix}-FRESH41-RESTART",
            as_of=AS_OF,
        )
        assert ledger.pending_order_ids == ("__GLOBAL_RECONCILIATION__",)
        decision = restarted_coordinator.recover_from_settlement_store(
            group_id=group_id,
            broker_snapshot=U19BrokerPositionSnapshot(
                group_id=group_id,
                snapshot_id=f"{suffix}-FRESH41-BROKER-PROXY",
                as_of=AS_OF,
                source="VALIDATION_ONLY:BROKER_EXCHANGE",
                positions=ledger.positions,
                complete=True,
                capability_verified=True,
                payload_sha256=("c" if suffix in {"FRESH40-A", "FRESH40-B"} else "d") * 64,
            ),
            snapshot_id=f"{suffix}-FRESH41-RESTART",
            as_of=AS_OF,
            ledger_snapshot_builder=builder,
        )
        assert decision.status is U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED
        assert decision.restore_allowed is False
        assert decision.pending_order_ids == ("__GLOBAL_RECONCILIATION__",)
        assert decision.new_entry_enabled is False
        assert decision.order_submission_enabled is False

    # FRESH-42: generic evidence labels and baseline APIs cannot bypass the
    # global collision gate; incoming-payload selection remains a manual
    # position-adjustment review, not an automatic journal rewrite.
    first_global = global_history[0]
    with pytest.raises(
        SettlementStoreError,
        match="EXECUTION_JOURNAL_CONFLICT_INCOMING_CANDIDATE_REQUIRES_POSITION_ADJUSTMENT_REVIEW",
    ):
        restarted_store.prepare_validation_only_execution_journal_conflict_resolution(
            execution_id=first_global["execution_id"],
            scope_key="__runtime_bootstrap__",
            original_payload_sha256=first_global["original_payload_sha256"],
            incoming_payload_sha256=first_global["incoming_payload_sha256"],
            selected_payload_sha256=first_global["incoming_payload_sha256"],
            evidence_ref="VALIDATION_ONLY:FRESH42:INCOMING_REQUIRES_POSITION_REVIEW",
        )

    with pytest.raises(
        SettlementStoreError,
        match="GLOBAL_RECONCILIATION_REQUIRES_DEDICATED_EVIDENCE_API",
    ):
        restarted_store.resolve_reconciliation(
            scope_key="__runtime_bootstrap__",
            authoritative_evidence_ref="VALIDATION_ONLY:FRESH42:GENERIC_BYPASS",
        )

    baseline_kwargs = {
        "positions_payload": (),
        "orders_snapshot_id": "SYNTHETIC:FRESH42:ORDERS",
        "executions_snapshot_id": "SYNTHETIC:FRESH42:EXECUTIONS",
        "positions_snapshot_id": "SYNTHETIC:FRESH42:POSITIONS",
        "as_of": AS_OF,
        "source": "VALIDATION_ONLY:FRESH42:BASELINE",
        "payload_sha256": "e" * 64,
        "authoritative_evidence_ref": "VALIDATION_ONLY:FRESH42:BASELINE_EVIDENCE",
    }
    with pytest.raises(
        SettlementStoreError,
        match="RUNTIME_BOOTSTRAP_CONFLICT_REQUIRES_MANUAL_REVIEW",
    ):
        restarted_store.establish_authoritative_baseline_snapshot(**baseline_kwargs)
    with pytest.raises(
        SettlementStoreError,
        match="RUNTIME_BOOTSTRAP_CONFLICT_REQUIRES_MANUAL_REVIEW",
    ):
        restarted_store.replace_validation_only_baseline_snapshot(
            expected_previous_payload_sha256="f" * 64,
            reset_reason="FRESH42 bypass attempt",
            **baseline_kwargs,
        )

    assert restarted_store.authoritative_baseline_evidence() is None
    assert len(restarted_store.execution_journal_conflict_history(
        scope_key="__runtime_bootstrap__"
    )) == 2
    assert restarted_store.unresolved_reconciliations()[0]["status"] == "CONFLICT"
    assert len(restarted_store.load_execution_journal_records()) == journal_count_before_restart

    # FRESH-44: a structurally valid validation-only packet may corroborate
    # conflict lineage, but it must never resolve the global gate or U19 state.
    from application.composition.validation_only_broker_evidence_packet import (
        ValidationOnlyBrokerEvidencePacketValidator,
    )

    packet_as_of = AS_OF.isoformat()
    packet = {
        "packet_id": "SYNTHETIC:FRESH44:GLOBAL-CONFLICT-PACKET",
        "source_namespace": "VALIDATION_ONLY:SYNTHETIC:FRESH44",
        "provider_ref": "VALIDATION_ONLY:FRESH44:FIXTURE_PROVIDER",
        "source_as_of": packet_as_of,
        "collected_at": packet_as_of,
        "snapshots": {
            "orders": {"snapshot_id": "FRESH44-ORDERS", "payload_sha256": "1" * 64, "complete": True},
            "executions": {"snapshot_id": "FRESH44-EXECUTIONS", "payload_sha256": "2" * 64, "complete": True},
            "positions": {"snapshot_id": "FRESH44-POSITIONS", "payload_sha256": "3" * 64, "complete": True},
        },
        "identity_crosswalk": [
            {
                "source_identity": {
                    "execution_id": item["execution_id"],
                    "client_order_id": item["incoming_client_order_id"],
                    "broker_order_id": item["incoming_broker_order_id"],
                },
                "internal_identity": {
                    "execution_id": item["execution_id"],
                    "scope_key": item["scope_key"],
                },
                "evidence_ref": f"VALIDATION_ONLY:FRESH44:CROSSWALK:{item['execution_id']}",
            }
            for item in global_history
        ],
        "conflict_links": [
            {
                "execution_id": item["execution_id"],
                "scope_key": item["scope_key"],
                "original_payload_sha256": item["original_payload_sha256"],
                "incoming_payload_sha256": item["incoming_payload_sha256"],
                "source_record_refs": [
                    f"journal:{item['execution_id']}",
                    f"conflict-event:{item['event_id']}",
                ],
            }
            for item in global_history
        ],
    }
    packet_result = ValidationOnlyBrokerEvidencePacketValidator(
        validation_only=True
    ).validate(packet=packet, as_of=AS_OF)
    assert packet_result.is_valid
    assert packet_result.manifest_sha256
    assert packet_result.gate_release_permitted is False
    assert packet_result.authoritative is False
    assert packet_result.mutation_applied is False
    packet_conflicts = {
        (
            item["execution_id"],
            item["scope_key"],
            item["original_payload_sha256"],
            item["incoming_payload_sha256"],
        )
        for item in packet_result.manifest["conflict_links"]
    }
    journal_conflicts = {
        (
            item["execution_id"],
            item["scope_key"],
            item["original_payload_sha256"],
            item["incoming_payload_sha256"],
        )
        for item in restarted_history
        if item["event_type"] == "CONFLICT_DETECTED"
    }
    assert packet_conflicts == journal_conflicts

    # Re-check every group after packet validation: no implicit adjudication.
    for group_id, position, suffix in groups:
        builder = ValidationOnlyU19LedgerSnapshotBuilder(restarted_store)
        ledger = builder.build(
            group_id=group_id,
            snapshot_id=f"{suffix}-FRESH44-PACKET-CHECK",
            as_of=AS_OF,
        )
        decision = restarted_coordinator.recover_from_settlement_store(
            group_id=group_id,
            broker_snapshot=U19BrokerPositionSnapshot(
                group_id=group_id,
                snapshot_id=f"{suffix}-FRESH44-BROKER-PROXY",
                as_of=AS_OF,
                source="VALIDATION_ONLY:BROKER_EXCHANGE",
                positions=ledger.positions,
                complete=True,
                capability_verified=True,
                payload_sha256=("a" if suffix in {"FRESH40-A", "FRESH40-B"} else "b") * 64,
            ),
            snapshot_id=f"{suffix}-FRESH44-PACKET-CHECK",
            as_of=AS_OF,
            ledger_snapshot_builder=builder,
        )
        assert decision.status is U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED
        assert decision.restore_allowed is False
        assert decision.pending_order_ids == ("__GLOBAL_RECONCILIATION__",)
        assert decision.new_entry_enabled is False
        assert decision.order_submission_enabled is False

    # FRESH-45: malformed/stale/future packets cannot alter preserved journal,
    # positions, or global U19 state.
    from copy import deepcopy
    from datetime import timedelta

    before_journal_count = len(restarted_store.load_execution_journal_records())
    before_position_quantities = {suffix: position.qty for _, position, suffix in groups}
    before_global_history = tuple(
        (
            item["execution_id"],
            item["scope_key"],
            item["original_payload_sha256"],
            item["incoming_payload_sha256"],
            item["event_type"],
        )
        for item in restarted_history
    )
    invalid_cases = []

    missing_snapshot = deepcopy(packet)
    missing_snapshot["snapshots"].pop("positions")
    invalid_cases.append((missing_snapshot, {}))

    duplicate_snapshot_id = deepcopy(packet)
    duplicate_snapshot_id["snapshots"]["executions"]["snapshot_id"] = "FRESH44-ORDERS"
    invalid_cases.append((duplicate_snapshot_id, {}))

    invalid_snapshot_hash = deepcopy(packet)
    invalid_snapshot_hash["snapshots"]["positions"]["payload_sha256"] = "invalid"
    invalid_cases.append((invalid_snapshot_hash, {}))

    mismatched_crosswalk = deepcopy(packet)
    mismatched_crosswalk["identity_crosswalk"][0]["internal_identity"]["execution_id"] = "SYNTHETIC:UNLINKED"
    invalid_cases.append((mismatched_crosswalk, {}))

    stale_anchor = deepcopy(packet)
    stale_anchor["source_as_of"] = (AS_OF - timedelta(seconds=60)).isoformat()
    stale_anchor["collected_at"] = AS_OF.isoformat()
    invalid_cases.append((stale_anchor, {"max_source_age_seconds": 30}))

    future_anchor = deepcopy(packet)
    future_at = (AS_OF + timedelta(seconds=60)).isoformat()
    future_anchor["source_as_of"] = future_at
    future_anchor["collected_at"] = future_at
    invalid_cases.append((future_anchor, {}))

    for invalid_packet, extra_args in invalid_cases:
        invalid_result = ValidationOnlyBrokerEvidencePacketValidator(
            validation_only=True
        ).validate(packet=invalid_packet, as_of=AS_OF, **extra_args)
        assert invalid_result.status == "RECONCILIATION_REQUIRED"
        assert invalid_result.is_valid is False
        assert invalid_result.gate_release_permitted is False
        assert invalid_result.authoritative is False
        assert invalid_result.mutation_applied is False

    assert len(restarted_store.load_execution_journal_records()) == before_journal_count
    assert {
        suffix: position.qty for _, position, suffix in groups
    } == before_position_quantities
    after_global_history = tuple(
        (
            item["execution_id"],
            item["scope_key"],
            item["original_payload_sha256"],
            item["incoming_payload_sha256"],
            item["event_type"],
        )
        for item in restarted_store.execution_journal_conflict_history(
            scope_key="__runtime_bootstrap__"
        )
    )
    assert after_global_history == before_global_history
    assert restarted_store.unresolved_reconciliations()[0]["status"] == "CONFLICT"

    for group_id, position, suffix in groups:
        builder = ValidationOnlyU19LedgerSnapshotBuilder(restarted_store)
        ledger = builder.build(
            group_id=group_id,
            snapshot_id=f"{suffix}-FRESH45-INVALID-PACKET-CHECK",
            as_of=AS_OF,
        )
        decision = restarted_coordinator.recover_from_settlement_store(
            group_id=group_id,
            broker_snapshot=U19BrokerPositionSnapshot(
                group_id=group_id,
                snapshot_id=f"{suffix}-FRESH45-BROKER-PROXY",
                as_of=AS_OF,
                source="VALIDATION_ONLY:BROKER_EXCHANGE",
                positions=ledger.positions,
                complete=True,
                capability_verified=True,
                payload_sha256=("e" if suffix in {"FRESH40-A", "FRESH40-B"} else "f") * 64,
            ),
            snapshot_id=f"{suffix}-FRESH45-INVALID-PACKET-CHECK",
            as_of=AS_OF,
            ledger_snapshot_builder=builder,
        )
        assert decision.status is U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED
        assert decision.restore_allowed is False
        assert decision.pending_order_ids == ("__GLOBAL_RECONCILIATION__",)
        assert decision.new_entry_enabled is False
        assert decision.order_submission_enabled is False
