from datetime import datetime, timezone
from decimal import Decimal

import pytest

from application.composition.track2_u19_ledger_snapshot_builder import (
    U19LedgerSnapshotBuildError,
    ValidationOnlyU19LedgerSnapshotBuilder,
)
from application.composition.track2_u19_recovery import ValidationOnlyTrack2U19RecoveryCoordinator
from contracts.types import BrokerOrderCommand, ExecutionReport, OrderAckEvent, OrderIntent
from core.oms.oms_fsm import OrderStateMachine
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
from environments.live.settlement.sqlite_settlement_store import SQLiteSettlementStore
from environments.virtual.position.track2_u19_recovery_store import SqliteTrack2U19RecoveryStore


AS_OF = datetime(2026, 11, 18, 10, 0, tzinfo=timezone.utc)
GROUP_ID = "SYNTHETIC:GROUP:U19-LEDGER"


def _order_with_fill(store, *, client_id, broker_id, instrument_id, side, leg_id, group_id=GROUP_ID,
                     fills=(("exec-1", 1, 0, "10.00"),)):
    oms = OrderStateMachine(persistence_store=store)
    quantity = sum(item[1] for item in fills)
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
    position = LivePositionAggregate(instrument_id)
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
