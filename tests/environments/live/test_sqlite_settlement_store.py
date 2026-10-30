from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from contracts.futures_contract_spec import FuturesProductType
from contracts.futures_identity_source_port import FuturesInstrumentIdentity
from contracts.types import BrokerOrderCommand, ExecutionReport, OrderAckEvent
from core.oms.oms_fsm import OrderStateMachine, OrderStateTransitionError
from core.oms.order_router import OrderRouterError, StandardOrderRouter
from environments.live.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.live.position.live_execution_position_bridge import (
    LiveExecutionPositionBridge,
    LivePositionFillAdapter,
)
from environments.live.position.live_position_aggregate import LivePositionAggregate
from environments.live.safety_gate import LiveSafetyGate
from core.risk.risk_guard import RiskGuard
from environments.live.settlement.sqlite_settlement_store import (
    SQLiteSettlementStore,
    SettlementStoreError,
)


def _prepared(tmp_path):
    store = SQLiteSettlementStore(tmp_path / "settlement.sqlite3")
    oms = OrderStateMachine(persistence_store=store)
    oms.apply_intent(type("Intent", (), {"client_order_id": "client-1", "quantity": 3})())
    command = BrokerOrderCommand(
        client_order_id="client-1",
        instrument_id="FUT-1",
        side="BUY",
        quantity=3,
        order_type="LIMIT",
        broker_symbol="FUT-1",
        asset_type="FUTURES",
        instrument_identity=FuturesInstrumentIdentity(
            instrument_id="FUT-1",
            symbol="FUT-1",
            product_type=FuturesProductType.MINI,
            contract_multiplier=Decimal("50000"),
            identity_source="TEST_FIXTURE",
        ),
        strategy_id="S1",
    )
    oms.register_broker_order_command(command)
    oms.apply_ack(OrderAckEvent(client_order_id="client-1", accepted=True, broker_order_id="broker-1"))
    position = LivePositionAggregate("FUT-1")
    dedup = ExecutionEventDeduplicator(persistence_store=store)
    bridge = LiveExecutionPositionBridge(
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(position),
        execution_event_deduplicator=dedup,
        position_aggregate=position,
        settlement_store=store,
    )
    return store, oms, position, dedup, bridge


def _fill(execution_id="exec-1", quantity=1, remaining=2, price="14.75", status="PARTIALLY_FILLED"):
    return ExecutionReport(
        client_order_id="client-1",
        broker_order_id="broker-1",
        execution_id=execution_id,
        status=status,
        filled_quantity=quantity,
        remaining_quantity=remaining,
        execution_price=Decimal(price),
        execution_timestamp=datetime(2026, 10, 29, 8, 54, tzinfo=timezone.utc),
    )


def test_sqlite_settlement_commits_fill_oms_position_and_dedup_together(tmp_path):
    store, oms, position, dedup, bridge = _prepared(tmp_path)

    state = bridge.settle(_fill())

    assert state.filled_quantity == 1
    assert state.status == "PARTIALLY_FILLED"
    assert position.qty == 1
    assert position.avg_price == Decimal("14.75")
    assert store.has_execution("exec-1")
    assert not store.has_unresolved_reconciliation()

    restarted_oms = OrderStateMachine(persistence_store=store)
    restarted_oms.restore_from_store()
    restarted_position = LivePositionAggregate("FUT-1")
    restarted_position.restore_persistence_record(store.load_position_state("FUT-1"))
    assert restarted_oms.get("client-1").filled_quantity == 1
    assert restarted_oms.get_broker_order_command("broker-1").instrument_id == "FUT-1"
    assert restarted_position.snapshot() == position.snapshot()


def test_duplicate_execution_after_restart_does_not_apply_position_twice(tmp_path):
    store, oms, position, dedup, bridge = _prepared(tmp_path)
    bridge.settle(_fill())

    restarted_oms = OrderStateMachine(persistence_store=store)
    restarted_oms.restore_from_store()
    restarted_position = LivePositionAggregate("FUT-1")
    restarted_position.restore_persistence_record(store.load_position_state("FUT-1"))
    restarted_bridge = LiveExecutionPositionBridge(
        order_state_machine=restarted_oms,
        position_fill_adapter=LivePositionFillAdapter(restarted_position),
        execution_event_deduplicator=ExecutionEventDeduplicator(persistence_store=store),
        position_aggregate=restarted_position,
        settlement_store=store,
    )

    state = restarted_bridge.settle(_fill())

    assert state.filled_quantity == 1
    assert restarted_position.qty == 1
    assert restarted_position.avg_price == Decimal("14.75")


def test_sqlite_failure_rolls_back_journal_and_leaves_memory_unchanged(tmp_path):
    store, oms, position, dedup, bridge = _prepared(tmp_path)
    with store._connection() as connection:
        connection.execute(
            """CREATE TRIGGER fail_position_insert BEFORE INSERT ON position_states
               BEGIN SELECT RAISE(ABORT, 'forced transaction failure'); END"""
        )

    with pytest.raises(SettlementStoreError, match="SETTLEMENT_TRANSACTION_FAILED"):
        bridge.settle(_fill())

    assert not store.has_execution("exec-1")
    assert oms.get("client-1").filled_quantity == 0
    assert position.qty == 0
    assert not dedup.contains("exec-1")
    assert store.has_unresolved_reconciliation()


def test_late_fill_is_durable_pending_and_blocks_router_until_authoritatively_resolved(tmp_path):
    store, oms, position, dedup, bridge = _prepared(tmp_path)
    bridge.settle(_fill())
    oms.apply_cancel(
        ExecutionReport(
            client_order_id="client-1",
            broker_order_id="broker-1",
            execution_id=None,
            status="CANCELLED",
            filled_quantity=0,
            remaining_quantity=2,
            execution_price=None,
            execution_timestamp=datetime(2026, 10, 29, 8, 55, tzinfo=timezone.utc),
        )
    )
    late = _fill(execution_id="exec-late", quantity=1, remaining=1, price="14.80")

    with pytest.raises(OrderStateTransitionError, match="RECONCILIATION_PENDING"):
        bridge.settle(late)

    assert store.has_unresolved_reconciliation()
    router = StandardOrderRouter(order_state_machine=oms, broker_adapter=object(), reconciliation_guard=store)
    command = oms.get_broker_order_command("broker-1")
    with pytest.raises(OrderRouterError, match="UNRESOLVED_EXECUTION_RECONCILIATION"):
        router.register_and_route(command, object())


def test_authoritative_late_fill_commits_and_resolves_pending_in_one_transaction(tmp_path):
    store, oms, position, dedup, bridge = _prepared(tmp_path)
    bridge.settle(_fill())
    oms.apply_cancel(
        ExecutionReport(
            client_order_id="client-1",
            broker_order_id="broker-1",
            execution_id=None,
            status="CANCELLED",
            filled_quantity=0,
            remaining_quantity=2,
            execution_price=None,
            execution_timestamp=datetime(2026, 10, 29, 8, 55, tzinfo=timezone.utc),
        )
    )
    late = _fill(execution_id="exec-late", quantity=1, remaining=1, price="14.80")
    with pytest.raises(OrderStateTransitionError, match="RECONCILIATION_PENDING"):
        bridge.settle(late)

    state = bridge.settle_authoritatively_reconciled_fill(
        late,
        authoritative_evidence_ref="offline-authoritative-evidence:case-001",
    )

    assert state.status == "CANCELLED"
    assert state.filled_quantity == 2
    assert position.qty == 2
    assert position.avg_price == Decimal("14.775")
    assert store.has_execution("exec-late")
    assert not store.has_unresolved_reconciliation()

def test_empty_database_is_fail_closed_until_authoritative_baseline_is_established(tmp_path):
    store = SQLiteSettlementStore(tmp_path / "empty.sqlite3")
    store.ensure_authoritative_baseline_gate()
    assert store.has_unresolved_reconciliation()

    store.establish_authoritative_baseline(
        position_payload={
            "instrument_id": "FUT-1",
            "side": None,
            "qty": 0,
            "avg_price": None,
        },
        authoritative_evidence_ref="offline-authoritative-baseline:case-002",
    )
    assert not store.has_unresolved_reconciliation()
    store.ensure_authoritative_baseline_gate()
    assert not store.has_unresolved_reconciliation()


def test_order_state_is_not_mutated_when_durable_write_fails(tmp_path, monkeypatch):
    store = SQLiteSettlementStore(tmp_path / "write-failure.sqlite3")
    oms = OrderStateMachine(persistence_store=store)

    def fail_write(*args, **kwargs):
        raise SettlementStoreError("forced durable write failure")

    monkeypatch.setattr(store, "save_order_state", fail_write)
    with pytest.raises(SettlementStoreError, match="forced durable write failure"):
        oms.apply_intent(type("Intent", (), {"client_order_id": "client-fail", "quantity": 1})())
    assert oms.get("client-fail") is None

def test_live_safety_gate_blocks_new_exposure_when_reconciliation_is_unresolved(tmp_path):
    store = SQLiteSettlementStore(tmp_path / "gate.sqlite3")
    store.mark_reconciliation_pending(
        scope_key="client-1",
        client_order_id="client-1",
        broker_order_id="broker-1",
        reason="TEST_LATE_FILL_PENDING",
        payload={"execution_id": "late-1"},
    )
    gate = LiveSafetyGate(
        policy=object(),
        risk_guard=RiskGuard(),
        sensor_max_delay_seconds=30,
        approval_validity_seconds=900,
        now=lambda: datetime.now(timezone.utc),
        allow_liquidation_reduction=True,
        reconciliation_guard=store,
    )
    result = gate.evaluate(1)
    assert not result.allowed
    assert result.reason == "UNRESOLVED_EXECUTION_RECONCILIATION"

def test_order_level_recovery_snapshot_is_not_committed_as_individual_execution(tmp_path):
    store, oms, position, dedup, bridge = _prepared(tmp_path)
    snapshot_report = _fill(execution_id="REST-CCNL-SNAPSHOT|broker-1|2|14.75")

    with pytest.raises(
        OrderStateTransitionError,
        match="ORDER_LEVEL_SNAPSHOT_REQUIRES_RECONCILIATION",
    ):
        bridge.settle(snapshot_report)

    assert oms.get("client-1").filled_quantity == 0
    assert position.qty == 0
    assert not store.has_execution(snapshot_report.execution_id)
    assert store.has_unresolved_reconciliation()

def test_startup_reconciliation_gate_is_persisted_as_valid_json(tmp_path):
    store = SQLiteSettlementStore(tmp_path / "startup.sqlite3")
    store.mark_startup_reconciliation_pending()
    unresolved = store.unresolved_reconciliations()
    assert len(unresolved) == 1
    assert unresolved[0]["scope_key"] == "__startup_reconciliation__"
    assert unresolved[0]["payload"] == {"requirement": "orders_fills_positions"}

def test_reused_execution_id_with_different_payload_is_conflict_not_duplicate(tmp_path):
    store, oms, position, dedup, bridge = _prepared(tmp_path)
    bridge.settle(_fill())
    with pytest.raises(SettlementStoreError, match="EXECUTION_ID_COLLISION"):
        bridge.settle(_fill(price="14.80"))

    assert oms.get("client-1").filled_quantity == 1
    assert position.qty == 1
    assert store.has_unresolved_reconciliation()

def test_live_position_composition_requires_and_shares_persistent_store(tmp_path):
    from application.composition.live_execution_position_composition_factory import (
        create_live_execution_position_composition,
    )

    store = SQLiteSettlementStore(tmp_path / "composition.sqlite3")
    oms = OrderStateMachine()
    position = LivePositionAggregate("FUT-1")
    composition = create_live_execution_position_composition(
        execution_source=object(),
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(position),
        execution_event_deduplicator=ExecutionEventDeduplicator(),
        position_aggregate=position,
        settlement_store=store,
    )

    assert composition.settlement_store is store
    assert store.has_unresolved_reconciliation()
    oms.apply_intent(type("Intent", (), {"client_order_id": "persisted-intent", "quantity": 1})())
    assert store.load_order_state_payloads()[0]["client_order_id"] == "persisted-intent"
