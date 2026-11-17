from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
import sqlite3

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


def test_cancelled_order_late_fill_inbox_is_append_only_and_survives_restart(tmp_path):
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
    late_one = _fill(execution_id="exec-late-1", quantity=1, remaining=1, price="14.80")
    late_two = _fill(execution_id="exec-late-2", quantity=1, remaining=0, price="14.85")

    for report in (late_one, late_two):
        with pytest.raises(OrderStateTransitionError, match="RECONCILIATION_PENDING"):
            bridge.settle(report)

    events = store.pending_reconciliation_events(scope_key="client-1")
    assert [event["execution_id"] for event in events] == ["exec-late-1", "exec-late-2"]
    assert all(event["payload"]["source_authority"] == "UNVERIFIED_PENDING_RECONCILIATION" for event in events)
    assert not store.has_execution("exec-late-1")
    assert not store.has_execution("exec-late-2")
    assert oms.get("client-1").status == "CANCELLED"
    assert oms.get("client-1").filled_quantity == 1
    assert position.qty == 1
    assert store.has_unresolved_reconciliation()

    # Reopen the durable store and rebuild only the persisted OMS/position projections.
    restarted_store = SQLiteSettlementStore(tmp_path / "settlement.sqlite3")
    restarted_oms = OrderStateMachine(persistence_store=restarted_store)
    restarted_oms.restore_from_store()
    restarted_position = LivePositionAggregate("FUT-1")
    restarted_position.restore_persistence_record(restarted_store.load_position_state("FUT-1"))
    restarted_bridge = LiveExecutionPositionBridge(
        order_state_machine=restarted_oms,
        position_fill_adapter=LivePositionFillAdapter(restarted_position),
        execution_event_deduplicator=ExecutionEventDeduplicator(persistence_store=restarted_store),
        position_aggregate=restarted_position,
        settlement_store=restarted_store,
    )

    with pytest.raises(OrderStateTransitionError, match="RECONCILIATION_PENDING"):
        restarted_bridge.settle(late_one)

    restored_events = restarted_store.pending_reconciliation_events(scope_key="client-1")
    assert [event["execution_id"] for event in restored_events] == ["exec-late-1", "exec-late-2"]
    assert restarted_oms.get("client-1").status == "CANCELLED"
    assert restarted_oms.get("client-1").filled_quantity == 1
    assert restarted_position.qty == 1
    assert restarted_store.has_unresolved_reconciliation()


def test_late_fill_inbox_execution_id_collision_is_preserved_as_conflict(tmp_path):
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
    first = _fill(execution_id="exec-late-collision", quantity=1, remaining=1, price="14.80")
    with pytest.raises(OrderStateTransitionError, match="RECONCILIATION_PENDING"):
        bridge.settle(first)

    conflicting = _fill(execution_id="exec-late-collision", quantity=1, remaining=1, price="14.90")
    with pytest.raises(SettlementStoreError, match="RECONCILIATION_INBOX_EXECUTION_ID_COLLISION"):
        bridge.settle(conflicting)

    later_unique = _fill(execution_id="exec-late-after-conflict", quantity=1, remaining=1, price="14.82")
    with pytest.raises(OrderStateTransitionError, match="RECONCILIATION_PENDING"):
        bridge.settle(later_unique)

    assert len(store.pending_reconciliation_events(scope_key="client-1")) == 1
    unresolved = store.unresolved_reconciliations()
    assert any(item["status"] == "CONFLICT" and item["reason"] == "RECONCILIATION_INBOX_EXECUTION_ID_COLLISION" for item in unresolved)
    assert oms.get("client-1").filled_quantity == 1
    assert position.qty == 1


def test_late_fill_settlement_resolves_inbox_only_after_every_event_is_settled(tmp_path):
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
    late_one = _fill(execution_id="exec-late-settle-1", quantity=1, remaining=1, price="14.80")
    late_two = _fill(execution_id="exec-late-settle-2", quantity=1, remaining=0, price="14.85")
    for report in (late_one, late_two):
        with pytest.raises(OrderStateTransitionError, match="RECONCILIATION_PENDING"):
            bridge.settle(report)

    # Test-only simulated inquiry evidence; this is not real KIS/broker evidence.
    first_state = bridge.settle_authoritatively_reconciled_fill(
        late_one,
        authoritative_evidence_ref="TEST_ONLY:simulated_external_inquiry:late-fill-1",
    )
    assert first_state.filled_quantity == 2
    assert [event["execution_id"] for event in store.pending_reconciliation_events(scope_key="client-1")] == [
        "exec-late-settle-2"
    ]
    assert store.has_unresolved_reconciliation()

    final_state = bridge.settle_authoritatively_reconciled_fill(
        late_two,
        authoritative_evidence_ref="TEST_ONLY:simulated_external_inquiry:late-fill-2",
    )
    assert final_state.filled_quantity == 3
    assert position.qty == 3
    assert store.pending_reconciliation_events(scope_key="client-1") == ()
    assert not store.has_unresolved_reconciliation()

    restarted_store = SQLiteSettlementStore(tmp_path / "settlement.sqlite3")
    restarted_oms = OrderStateMachine(persistence_store=restarted_store)
    restarted_oms.restore_from_store()
    restarted_position = LivePositionAggregate("FUT-1")
    restarted_position.restore_persistence_record(restarted_store.load_position_state("FUT-1"))
    assert restarted_oms.get("client-1").status == "CANCELLED"
    assert restarted_oms.get("client-1").filled_quantity == 3
    assert restarted_position.qty == 3
    assert restarted_store.pending_reconciliation_events(scope_key="client-1") == ()

    # A post-settlement replay must match the original journal payload and stay idempotent.
    replay_state = bridge.settle(late_one)
    assert replay_state.filled_quantity == 3
    assert position.qty == 3
    restarted_replay_state = LiveExecutionPositionBridge(
        order_state_machine=restarted_oms,
        position_fill_adapter=LivePositionFillAdapter(restarted_position),
        execution_event_deduplicator=ExecutionEventDeduplicator(persistence_store=restarted_store),
        position_aggregate=restarted_position,
        settlement_store=restarted_store,
    ).settle(late_one)
    assert restarted_replay_state.filled_quantity == 3
    assert restarted_position.qty == 3


def test_generic_reconciliation_cannot_clear_open_late_fill_inbox(tmp_path):
    store = SQLiteSettlementStore(tmp_path / "settlement.sqlite3")
    store.record_late_fill_pending(
        execution_id="exec-open-1",
        client_order_id="client-open",
        broker_order_id="broker-open",
        payload={"execution_id": "exec-open-1", "source_authority": "VALIDATION_ONLY"},
    )
    with pytest.raises(SettlementStoreError, match="RECONCILIATION_INBOX_EVENTS_MUST_BE_SETTLED_INDIVIDUALLY"):
        store.resolve_reconciliation(
            scope_key="client-open",
            authoritative_evidence_ref="TEST_ONLY:must-not-clear-inbox",
        )
    assert store.has_unresolved_reconciliation()
    assert len(store.open_reconciliation_events(scope_key="client-open")) == 1



def test_startup_reconciliation_requires_three_distinct_aligned_snapshots_and_dedicated_gate(tmp_path):
    from datetime import datetime, timezone

    store = SQLiteSettlementStore(tmp_path / "startup-three-snapshots.sqlite3")
    store.ensure_authoritative_baseline_gate()
    with pytest.raises(SettlementStoreError, match="GLOBAL_RECONCILIATION_REQUIRES_DEDICATED_EVIDENCE_API"):
        store.resolve_reconciliation(
            scope_key="__runtime_bootstrap__", authoritative_evidence_ref="TEST_ONLY:bypass"
        )
    with pytest.raises(SettlementStoreError, match="AUTHORITATIVE_BASELINE_REQUIRED_BEFORE_STARTUP_RECONCILIATION"):
        store.resolve_startup_reconciliation(
            orders_snapshot_id="orders-1", executions_snapshot_id="fills-1",
            positions_snapshot_id="positions-1", as_of=datetime(2026, 11, 18, 10, 0, tzinfo=timezone.utc),
            source="VALIDATION_ONLY:STARTUP_SNAPSHOT", payload_sha256="a" * 64,
            authoritative_evidence_ref="TEST_ONLY:startup-evidence",
        )

    store.establish_authoritative_baseline(
        position_payload={"instrument_id": "OPT-BASE", "side": None, "qty": 0, "avg_price": None},
        authoritative_evidence_ref="TEST_ONLY:baseline-position",
    )
    store.mark_startup_reconciliation_pending()
    with pytest.raises(SettlementStoreError, match="GLOBAL_RECONCILIATION_REQUIRES_DEDICATED_EVIDENCE_API"):
        store.resolve_reconciliation(
            scope_key="__startup_reconciliation__", authoritative_evidence_ref="TEST_ONLY:bypass"
        )

    as_of = datetime(2026, 11, 18, 10, 0, tzinfo=timezone.utc)
    common = {
        "orders_snapshot_id": "orders-20261118-1000",
        "executions_snapshot_id": "fills-20261118-1000",
        "positions_snapshot_id": "positions-20261118-1000",
        "as_of": as_of,
        "source": "VALIDATION_ONLY:STARTUP_SNAPSHOT",
        "payload_sha256": "b" * 64,
        "authoritative_evidence_ref": "TEST_ONLY:orders-fills-positions-matched",
    }
    with pytest.raises(ValueError, match="STARTUP_ORDERS_EXECUTIONS_POSITIONS_SNAPSHOT_IDS_REQUIRED_AND_DISTINCT"):
        store.resolve_startup_reconciliation(**{**common, "executions_snapshot_id": "orders-20261118-1000"})
    with pytest.raises(ValueError, match="STARTUP_RECONCILIATION_SHA256_INVALID"):
        store.resolve_startup_reconciliation(**{**common, "payload_sha256": "not-a-hash"})
    with pytest.raises(ValueError, match="STARTUP_RECONCILIATION_AS_OF_MUST_BE_TIMEZONE_AWARE"):
        store.resolve_startup_reconciliation(**{**common, "as_of": datetime(2026, 11, 18, 10, 0)})

    assert store.resolve_startup_reconciliation(**common) is True
    assert store.resolve_startup_reconciliation(**common) is False
    assert not store.has_unresolved_reconciliation()
    with sqlite3.connect(store.path) as connection:
        evidence = connection.execute(
            "SELECT value FROM settlement_meta WHERE key='startup_reconciliation_evidence'"
        ).fetchone()[0]
    decoded = json.loads(evidence)
    assert decoded["coverage"] == ["orders", "fills", "positions"]
    assert decoded["orders_snapshot_id"] == common["orders_snapshot_id"]


def test_startup_gate_conflict_is_not_downgraded_by_repeated_startup_mark(tmp_path):
    from datetime import datetime, timezone

    store = SQLiteSettlementStore(tmp_path / "startup-conflict.sqlite3")
    store.establish_authoritative_baseline(
        position_payload={"instrument_id": "OPT-BASE", "side": None, "qty": 0, "avg_price": None},
        authoritative_evidence_ref="TEST_ONLY:baseline-position",
    )
    store.mark_startup_reconciliation_pending()
    store.mark_reconciliation_pending(
        scope_key="__startup_reconciliation__",
        client_order_id="__startup_reconciliation__",
        broker_order_id=None,
        reason="TEST_STARTUP_CONFLICT",
        payload={"conflict": True},
        conflict=True,
    )
    store.mark_startup_reconciliation_pending()
    unresolved = store.unresolved_reconciliations()
    assert len(unresolved) == 1
    assert unresolved[0]["status"] == "CONFLICT"
    with pytest.raises(SettlementStoreError, match="STARTUP_RECONCILIATION_CONFLICT_REQUIRES_MANUAL_REVIEW"):
        store.resolve_startup_reconciliation(
            orders_snapshot_id="orders-1", executions_snapshot_id="fills-1",
            positions_snapshot_id="positions-1", as_of=datetime(2026, 11, 18, 10, 0, tzinfo=timezone.utc),
            source="VALIDATION_ONLY:STARTUP_SNAPSHOT", payload_sha256="c" * 64,
            authoritative_evidence_ref="TEST_ONLY:must-not-clear-conflict",
        )


def test_authoritative_baseline_does_not_clear_runtime_bootstrap_conflict(tmp_path):
    store = SQLiteSettlementStore(tmp_path / "bootstrap-conflict.sqlite3")
    store.ensure_authoritative_baseline_gate()
    store.mark_reconciliation_pending(
        scope_key="__runtime_bootstrap__",
        client_order_id="__runtime_bootstrap__",
        broker_order_id=None,
        reason="TEST_BOOTSTRAP_CONFLICT",
        payload={"conflict": True},
        conflict=True,
    )
    with pytest.raises(SettlementStoreError, match="AUTHORITATIVE_BASELINE_TRANSACTION_FAILED"):
        store.establish_authoritative_baseline(
            position_payload={"instrument_id": "OPT-BASE", "side": None, "qty": 0, "avg_price": None},
            authoritative_evidence_ref="TEST_ONLY:must-not-clear-bootstrap-conflict",
        )
    unresolved = store.unresolved_reconciliations()
    assert len(unresolved) == 1
    assert unresolved[0]["scope_key"] == "__runtime_bootstrap__"
    assert unresolved[0]["status"] == "CONFLICT"
