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


def test_multi_instrument_baseline_snapshot_import_is_atomic_and_keeps_startup_gate(tmp_path):
    from datetime import datetime, timezone

    store = SQLiteSettlementStore(tmp_path / "multi-instrument-baseline.sqlite3")
    store.ensure_authoritative_baseline_gate()
    store.establish_authoritative_baseline_snapshot(
        positions_payload=(
            {"instrument_id": "OPT-CALL", "side": "LONG", "qty": 2, "avg_price": "10.25"},
            {"instrument_id": "OPT-PUT", "side": "SHORT", "qty": 1, "avg_price": "7.50"},
            {"instrument_id": "FUT-NEAR", "side": None, "qty": 0, "avg_price": None},
        ),
        orders_snapshot_id="TEST_ONLY:baseline-orders-1",
        executions_snapshot_id="TEST_ONLY:baseline-fills-1",
        positions_snapshot_id="TEST_ONLY:baseline-positions-1",
        as_of=datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc),
        source="VALIDATION_ONLY:ACCOUNT_BASELINE",
        payload_sha256="e" * 64,
        authoritative_evidence_ref="TEST_ONLY:complete-multi-instrument-baseline",
    )
    with sqlite3.connect(store.path) as connection:
        rows = connection.execute(
            "SELECT instrument_id,position_json FROM position_states ORDER BY instrument_id"
        ).fetchall()
        baseline_ready = connection.execute(
            "SELECT value FROM settlement_meta WHERE key='authoritative_baseline_ready'"
        ).fetchone()[0]
    assert len(rows) == 3
    assert baseline_ready == "1"
    assert {instrument_id for instrument_id, _ in rows} == {"OPT-CALL", "OPT-PUT", "FUT-NEAR"}
    assert not store.has_unresolved_reconciliation()

    # The bootstrap baseline does not release the separate per-startup gate.
    store.mark_startup_reconciliation_pending()
    assert store.has_unresolved_reconciliation()


def test_multi_instrument_baseline_rejects_duplicate_identity_without_partial_write(tmp_path):
    from datetime import datetime, timezone

    store = SQLiteSettlementStore(tmp_path / "invalid-multi-baseline.sqlite3")
    store.ensure_authoritative_baseline_gate()
    with pytest.raises(ValueError, match="BASELINE_POSITION_INSTRUMENT_ID_MISSING_OR_DUPLICATE"):
        store.establish_authoritative_baseline_snapshot(
            positions_payload=(
                {"instrument_id": "OPT-CALL", "side": "LONG", "qty": 1, "avg_price": "10.00"},
                {"instrument_id": "OPT-CALL", "side": "LONG", "qty": 2, "avg_price": "10.10"},
            ),
            orders_snapshot_id="TEST_ONLY:orders-1",
            executions_snapshot_id="TEST_ONLY:fills-1",
            positions_snapshot_id="TEST_ONLY:positions-1",
            as_of=datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc),
            source="VALIDATION_ONLY:ACCOUNT_BASELINE",
            payload_sha256="f" * 64,
            authoritative_evidence_ref="TEST_ONLY:invalid-duplicate-instrument",
        )
    with sqlite3.connect(store.path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM position_states").fetchone()[0]
        baseline = connection.execute(
            "SELECT value FROM settlement_meta WHERE key='authoritative_baseline_ready'"
        ).fetchone()
    assert count == 0
    assert baseline is None
    assert store.has_unresolved_reconciliation()


def test_multi_instrument_baseline_import_does_not_clear_existing_order_inbox(tmp_path):
    from datetime import datetime, timezone

    store = SQLiteSettlementStore(tmp_path / "baseline-open-inbox.sqlite3")
    store.ensure_authoritative_baseline_gate()
    store.record_reconciliation_event_pending(
        event_id="REST-CCNL-SNAPSHOT|broker-open|1|10.00",
        client_order_id="client-open",
        broker_order_id="broker-open",
        event_kind="KIS_REST_CUMULATIVE_ORDER_SNAPSHOT",
        payload={"cumulative_filled_quantity": 1},
    )
    with pytest.raises(SettlementStoreError, match="BASELINE_IMPORT_HAS_OTHER_UNRESOLVED_RECONCILIATION"):
        store.establish_authoritative_baseline_snapshot(
            positions_payload=(),
            orders_snapshot_id="TEST_ONLY:orders-1",
            executions_snapshot_id="TEST_ONLY:fills-1",
            positions_snapshot_id="TEST_ONLY:positions-1",
            as_of=datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc),
            source="VALIDATION_ONLY:ACCOUNT_BASELINE",
            payload_sha256="f" * 64,
            authoritative_evidence_ref="TEST_ONLY:must-not-clear-open-order",
        )
    assert store.has_unresolved_reconciliation()
    with sqlite3.connect(store.path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM position_states").fetchone()[0]
        baseline = connection.execute(
            "SELECT value FROM settlement_meta WHERE key='authoritative_baseline_ready'"
        ).fetchone()
    assert count == 0
    assert baseline is None

def test_live_composition_reapplies_startup_gate_after_restart(tmp_path):
    from datetime import datetime, timezone
    from application.composition.live_execution_position_composition_factory import (
        create_live_execution_position_composition,
    )

    store = SQLiteSettlementStore(tmp_path / "composition-restart-baseline.sqlite3")
    store.establish_authoritative_baseline_snapshot(
        positions_payload=(
            {"instrument_id": "OPT-CALL", "side": "LONG", "qty": 1, "avg_price": "10.00"},
            {"instrument_id": "OPT-PUT", "side": "SHORT", "qty": 1, "avg_price": "8.00"},
        ),
        orders_snapshot_id="TEST_ONLY:baseline-orders",
        executions_snapshot_id="TEST_ONLY:baseline-fills",
        positions_snapshot_id="TEST_ONLY:baseline-positions",
        as_of=datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc),
        source="VALIDATION_ONLY:ACCOUNT_BASELINE",
        payload_sha256="d" * 64,
        authoritative_evidence_ref="TEST_ONLY:baseline-complete",
    )

    def compose():
        position = LivePositionAggregate("OPT-CALL")
        return create_live_execution_position_composition(
            execution_source=object(),
            order_state_machine=OrderStateMachine(),
            position_fill_adapter=LivePositionFillAdapter(position),
            execution_event_deduplicator=ExecutionEventDeduplicator(),
            position_aggregate=position,
            settlement_store=store,
        )

    first = compose()
    assert first.settlement_store is store
    assert store.has_unresolved_reconciliation()
    store.resolve_startup_reconciliation(
        orders_snapshot_id="TEST_ONLY:startup-orders-1",
        executions_snapshot_id="TEST_ONLY:startup-fills-1",
        positions_snapshot_id="TEST_ONLY:startup-positions-1",
        as_of=datetime(2026, 11, 18, 9, 5, tzinfo=timezone.utc),
        source="VALIDATION_ONLY:STARTUP_SNAPSHOT",
        payload_sha256="e" * 64,
        authoritative_evidence_ref="TEST_ONLY:first-startup-reconciliation",
    )
    assert not store.has_unresolved_reconciliation()

    # A fresh composition represents a new process start and must re-open the gate.
    second = compose()
    assert second.settlement_store is store
    assert store.has_unresolved_reconciliation()
    unresolved = store.unresolved_reconciliations()
    assert any(item["scope_key"] == "__startup_reconciliation__" and item["status"] == "PENDING" for item in unresolved)


def test_individual_multifill_journal_oms_position_restart_replay_exactly_once(tmp_path):
    store, oms, position, dedup, bridge = _prepared(tmp_path)
    first = _fill(execution_id="multi-fill-1", quantity=1, remaining=2, price="14.75")
    second = _fill(
        execution_id="multi-fill-2",
        quantity=2,
        remaining=0,
        price="14.85",
        status="FILLED",
    )

    first_state = bridge.settle(first)
    assert first_state.filled_quantity == 1
    assert first_state.average_execution_price == Decimal("14.75")
    assert position.qty == 1
    assert position.avg_price == Decimal("14.75")
    first_rows = store.load_execution_journal_records()
    assert [row["execution_id"] for row in first_rows] == ["multi-fill-1"]
    first_fingerprint = first_rows[0]["report_json"]

    # Simulate process restart between two distinct individual fill events.
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

    final_state = restarted_bridge.settle(second)
    expected_average = (Decimal("14.75") + Decimal("14.85") * 2) / Decimal(3)
    assert final_state.status == "FILLED"
    assert final_state.filled_quantity == 3
    assert final_state.average_execution_price == expected_average
    assert restarted_position.qty == 3
    assert restarted_position.avg_price == expected_average

    rows = restarted_store.load_execution_journal_records()
    assert [row["execution_id"] for row in rows] == ["multi-fill-1", "multi-fill-2"]
    assert rows[0]["report_json"] == first_fingerprint
    fingerprints = {
        row["execution_id"]: __import__("hashlib").sha256(row["report_json"].encode("utf-8")).hexdigest()
        for row in rows
    }
    assert len(set(fingerprints.values())) == 2

    # Replaying either committed fill after restart must not alter OMS or position.
    replay_first = restarted_bridge.settle(first)
    replay_second = restarted_bridge.settle(second)
    assert replay_first.filled_quantity == replay_second.filled_quantity == 3
    assert restarted_position.qty == 3
    assert restarted_position.avg_price == expected_average
    assert len(restarted_store.load_execution_journal_records()) == 2
    persisted_order = restarted_store.load_order_state_payloads()[0]
    persisted_position = restarted_store.load_position_state("FUT-1")
    assert persisted_order["filled_quantity"] == 3
    assert persisted_order["average_execution_price"] == str(expected_average)
    assert persisted_position["qty"] == 3
    assert persisted_position["avg_price"] == str(expected_average)


def test_post_commit_memory_projection_failure_restores_durable_state_after_restart(tmp_path, monkeypatch):
    store, oms, position, dedup, bridge = _prepared(tmp_path)
    report = _fill(execution_id="commit-before-crash", quantity=1, remaining=2)

    def crash_projection(_snapshot):
        raise RuntimeError("synthetic process interruption after database commit")

    monkeypatch.setattr(position, "restore_snapshot", crash_projection)
    with pytest.raises(RuntimeError, match="SETTLEMENT_COMMITTED_MEMORY_PROJECTION_REBUILD_REQUIRED"):
        bridge.settle(report)

    assert store.has_execution("commit-before-crash")
    assert store.load_order_state_payloads()[0]["filled_quantity"] == 1
    assert store.load_position_state("FUT-1")["qty"] == 1
    assert oms.get("client-1").filled_quantity == 1
    assert position.qty == 0
    unresolved = store.unresolved_reconciliations()
    assert any(
        item["scope_key"] == "client-1"
        and item["status"] == "CONFLICT"
        and item["reason"] == "POST_COMMIT_MEMORY_PROJECTION_REBUILD_REQUIRED"
        for item in unresolved
    )

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
    replayed = restarted_bridge.settle(report)
    assert replayed.filled_quantity == 1
    assert restarted_position.qty == 1
    assert restarted_position.avg_price == Decimal("14.75")
    assert len(restarted_store.load_execution_journal_records()) == 1
    assert restarted_store.has_unresolved_reconciliation()


def test_second_fill_partial_sqlite_write_failure_rolls_back_all_durable_and_memory_state(tmp_path):
    store, oms, position, dedup, bridge = _prepared(tmp_path)
    bridge.settle(_fill(execution_id="first-commit", quantity=1, remaining=2))
    before_order = store.load_order_state_payloads()[0]
    before_position = store.load_position_state("FUT-1")

    with store._connection() as connection:
        connection.execute(
            """CREATE TRIGGER fail_position_update BEFORE UPDATE ON position_states
               BEGIN SELECT RAISE(ABORT, 'synthetic mid-transaction failure'); END"""
        )

    with pytest.raises(SettlementStoreError, match="SETTLEMENT_TRANSACTION_FAILED"):
        bridge.settle(_fill(execution_id="second-rollback", quantity=1, remaining=1, price="14.90"))

    assert [row["execution_id"] for row in store.load_execution_journal_records()] == ["first-commit"]
    assert store.load_order_state_payloads()[0] == before_order
    assert store.load_position_state("FUT-1") == before_position
    assert oms.get("client-1").filled_quantity == 1
    assert position.qty == 1
    assert not dedup.contains("second-rollback")


def test_shared_settlement_store_isolates_multiple_orders_and_instruments(tmp_path):
    store = SQLiteSettlementStore(tmp_path / "multi-order.sqlite3")
    oms = OrderStateMachine(persistence_store=store)
    aggregates = {}
    bridges = {}
    for index, instrument_id in enumerate(("OPT-CALL-100", "OPT-PUT-100"), start=1):
        client_order_id = f"client-{index}"
        broker_order_id = f"broker-{index}"
        oms.apply_intent(type("Intent", (), {"client_order_id": client_order_id, "quantity": 2})())
        command = BrokerOrderCommand(
            client_order_id=client_order_id,
            instrument_id=instrument_id,
            side="BUY" if index == 1 else "SELL",
            quantity=2,
            order_type="LIMIT",
            broker_symbol=instrument_id,
            asset_type="OPTIONS",
            instrument_identity=FuturesInstrumentIdentity(
                instrument_id=instrument_id,
                symbol=instrument_id,
                product_type=FuturesProductType.MINI,
                contract_multiplier=Decimal("50000"),
                identity_source="TEST_FIXTURE",
            ),
            strategy_id="SYNTHETIC-MULTI-INSTRUMENT",
        )
        oms.register_broker_order_command(command)
        oms.apply_ack(OrderAckEvent(client_order_id=client_order_id, accepted=True, broker_order_id=broker_order_id))
        aggregate = LivePositionAggregate(instrument_id)
        aggregates[instrument_id] = aggregate
        bridges[instrument_id] = LiveExecutionPositionBridge(
            order_state_machine=oms,
            position_fill_adapter=LivePositionFillAdapter(aggregate),
            execution_event_deduplicator=ExecutionEventDeduplicator(persistence_store=store),
            position_aggregate=aggregate,
            settlement_store=store,
        )

    reports = (
        ExecutionReport(
            client_order_id="client-1", broker_order_id="broker-1", execution_id="exec-call-1",
            status="PARTIALLY_FILLED", filled_quantity=1, remaining_quantity=1,
            execution_price=Decimal("10.25"), execution_timestamp=datetime(2026, 10, 29, 8, 54, tzinfo=timezone.utc),
        ),
        ExecutionReport(
            client_order_id="client-2", broker_order_id="broker-2", execution_id="exec-put-1",
            status="FILLED", filled_quantity=2, remaining_quantity=0,
            execution_price=Decimal("7.50"), execution_timestamp=datetime(2026, 10, 29, 8, 54, tzinfo=timezone.utc),
        ),
    )
    bridges["OPT-CALL-100"].settle(reports[0])
    bridges["OPT-PUT-100"].settle(reports[1])

    assert oms.get("client-1").filled_quantity == 1
    assert oms.get("client-2").filled_quantity == 2
    assert aggregates["OPT-CALL-100"].qty == 1
    assert aggregates["OPT-CALL-100"].avg_price == Decimal("10.25")
    assert aggregates["OPT-PUT-100"].qty == 2
    assert aggregates["OPT-PUT-100"].avg_price == Decimal("7.50")
    assert {row["execution_id"] for row in store.load_execution_journal_records()} == {"exec-call-1", "exec-put-1"}
    assert store.load_position_state("OPT-CALL-100")["qty"] == 1
    assert store.load_position_state("OPT-PUT-100")["qty"] == 2

    restarted_store = SQLiteSettlementStore(tmp_path / "multi-order.sqlite3")
    restarted_oms = OrderStateMachine(persistence_store=restarted_store)
    restarted_oms.restore_from_store()
    assert restarted_oms.get("client-1").filled_quantity == 1
    assert restarted_oms.get("client-2").filled_quantity == 2
    for instrument_id, expected_qty in (("OPT-CALL-100", 1), ("OPT-PUT-100", 2)):
        restored = LivePositionAggregate(instrument_id)
        restored.restore_persistence_record(restarted_store.load_position_state(instrument_id))
        assert restored.qty == expected_qty


def test_subprocess_hard_crash_after_sqlite_commit_recovers_from_wal(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    database = tmp_path / "hard-crash.sqlite3"
    child = r'''
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from contracts.futures_contract_spec import FuturesProductType
from contracts.futures_identity_source_port import FuturesInstrumentIdentity
from contracts.types import BrokerOrderCommand, ExecutionReport, OrderAckEvent
from core.oms.oms_fsm import OrderStateMachine
from environments.live.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.live.position.live_execution_position_bridge import LiveExecutionPositionBridge, LivePositionFillAdapter
from environments.live.position.live_position_aggregate import LivePositionAggregate
from environments.live.settlement.sqlite_settlement_store import SQLiteSettlementStore
store = SQLiteSettlementStore(Path(sys.argv[1]))
oms = OrderStateMachine(persistence_store=store)
oms.apply_intent(type("Intent", (), {"client_order_id": "child-order", "quantity": 2})())
command = BrokerOrderCommand(
    client_order_id="child-order", instrument_id="CHILD-FUT", side="BUY", quantity=2,
    order_type="LIMIT", broker_symbol="CHILD-FUT", asset_type="FUTURES",
    instrument_identity=FuturesInstrumentIdentity(
        instrument_id="CHILD-FUT", symbol="CHILD-FUT", product_type=FuturesProductType.MINI,
        contract_multiplier=Decimal("50000"), identity_source="TEST_FIXTURE",
    ), strategy_id="HARD-CRASH-TEST",
)
oms.register_broker_order_command(command)
oms.apply_ack(OrderAckEvent(client_order_id="child-order", accepted=True, broker_order_id="child-broker"))
position = LivePositionAggregate("CHILD-FUT")
bridge = LiveExecutionPositionBridge(
    order_state_machine=oms, position_fill_adapter=LivePositionFillAdapter(position),
    execution_event_deduplicator=ExecutionEventDeduplicator(persistence_store=store),
    position_aggregate=position, settlement_store=store,
)
report = ExecutionReport(
    client_order_id="child-order", broker_order_id="child-broker", execution_id="hard-crash-fill",
    status="PARTIALLY_FILLED", filled_quantity=1, remaining_quantity=1,
    execution_price=Decimal("21.50"), execution_timestamp=datetime(2026, 10, 29, 8, 54, tzinfo=timezone.utc),
)
def terminate_after_commit(_snapshot):
    os._exit(73)
position.restore_snapshot = terminate_after_commit
bridge.settle(report)
os._exit(74)
'''
    completed = subprocess.run(
        [sys.executable, "-c", child, str(database)],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 73, completed.stderr

    recovered_store = SQLiteSettlementStore(database)
    assert [row["execution_id"] for row in recovered_store.load_execution_journal_records()] == ["hard-crash-fill"]
    recovered_oms = OrderStateMachine(persistence_store=recovered_store)
    recovered_oms.restore_from_store()
    recovered_position = LivePositionAggregate("CHILD-FUT")
    recovered_position.restore_persistence_record(recovered_store.load_position_state("CHILD-FUT"))
    assert recovered_oms.get("child-order").filled_quantity == 1
    assert recovered_position.qty == 1
    assert recovered_position.avg_price == Decimal("21.50")
    replay_bridge = LiveExecutionPositionBridge(
        order_state_machine=recovered_oms,
        position_fill_adapter=LivePositionFillAdapter(recovered_position),
        execution_event_deduplicator=ExecutionEventDeduplicator(persistence_store=recovered_store),
        position_aggregate=recovered_position,
        settlement_store=recovered_store,
    )
    replay_report = ExecutionReport(
        client_order_id="child-order", broker_order_id="child-broker", execution_id="hard-crash-fill",
        status="PARTIALLY_FILLED", filled_quantity=1, remaining_quantity=1,
        execution_price=Decimal("21.50"), execution_timestamp=datetime(2026, 10, 29, 8, 54, tzinfo=timezone.utc),
    )
    replayed = replay_bridge.settle(replay_report)
    assert replayed.filled_quantity == 1
    assert recovered_position.qty == 1
    assert len(recovered_store.load_execution_journal_records()) == 1


def test_cross_order_execution_id_collision_persists_global_conflict_history(tmp_path):
    store, oms, position, dedup, first_bridge = _prepared(tmp_path)
    first_bridge.settle(_fill(execution_id="shared-execution-id", quantity=1, remaining=2))

    oms.apply_intent(type("Intent", (), {"client_order_id": "client-2", "quantity": 2})())
    second_command = BrokerOrderCommand(
        client_order_id="client-2", instrument_id="FUT-2", side="BUY", quantity=2,
        order_type="LIMIT", broker_symbol="FUT-2", asset_type="FUTURES",
        instrument_identity=FuturesInstrumentIdentity(
            instrument_id="FUT-2", symbol="FUT-2", product_type=FuturesProductType.MINI,
            contract_multiplier=Decimal("50000"), identity_source="TEST_FIXTURE",
        ), strategy_id="SYNTHETIC-COLLISION",
    )
    oms.register_broker_order_command(second_command)
    oms.apply_ack(OrderAckEvent(client_order_id="client-2", accepted=True, broker_order_id="broker-2"))
    second_position = LivePositionAggregate("FUT-2")
    second_bridge = LiveExecutionPositionBridge(
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(second_position),
        execution_event_deduplicator=ExecutionEventDeduplicator(persistence_store=store),
        position_aggregate=second_position,
        settlement_store=store,
    )
    conflicting_report = ExecutionReport(
        client_order_id="client-2", broker_order_id="broker-2", execution_id="shared-execution-id",
        status="PARTIALLY_FILLED", filled_quantity=1, remaining_quantity=1,
        execution_price=Decimal("8.25"), execution_timestamp=datetime(2026, 10, 29, 8, 55, tzinfo=timezone.utc),
    )
    with pytest.raises(SettlementStoreError, match="EXECUTION_ID_COLLISION"):
        second_bridge.settle(conflicting_report)

    history = store.execution_journal_conflict_history(execution_id="shared-execution-id")
    assert len(history) == 1
    assert history[0]["scope_key"] == "__runtime_bootstrap__"
    assert history[0]["original_client_order_id"] == "client-1"
    assert history[0]["incoming_client_order_id"] == "client-2"
    assert history[0]["original_payload_sha256"] != history[0]["incoming_payload_sha256"]
    assert [row["execution_id"] for row in store.load_execution_journal_records()] == ["shared-execution-id"]
    assert oms.get("client-1").filled_quantity == 1
    assert oms.get("client-2").filled_quantity == 0
    assert position.qty == 1
    assert second_position.qty == 0
    assert any(
        item["scope_key"] == "__runtime_bootstrap__" and item["status"] == "CONFLICT"
        for item in store.unresolved_reconciliations()
    )

    reopened = SQLiteSettlementStore(tmp_path / "settlement.sqlite3")
    persisted_history = reopened.execution_journal_conflict_history(execution_id="shared-execution-id")
    assert persisted_history == history
    assert any(
        item["scope_key"] == "__runtime_bootstrap__" and item["status"] == "CONFLICT"
        for item in reopened.unresolved_reconciliations()
    )


def test_individual_fill_fees_are_journaled_once_across_replay(tmp_path):
    from dataclasses import replace

    store, oms, position, dedup, bridge = _prepared(tmp_path)
    first = replace(_fill(execution_id="fee-fill-1", quantity=1, remaining=2, price="14.75"), fee=Decimal("0.12"))
    second = replace(_fill(execution_id="fee-fill-2", quantity=2, remaining=0, price="14.85", status="FILLED"), fee=Decimal("0.24"))
    bridge.settle(first)
    final_state = bridge.settle(second)
    records = store.load_execution_journal_records()
    assert [row["execution_id"] for row in records] == ["fee-fill-1", "fee-fill-2"]
    assert [__import__("json").loads(row["report_json"])["fee"] for row in records] == ["0.12", "0.24"]
    assert final_state.filled_quantity == 3
    assert position.qty == 3
    assert oms.get("client-1").filled_quantity == 3

    bridge.settle(first)
    bridge.settle(second)
    replayed = store.load_execution_journal_records()
    assert len(replayed) == 2
    assert [__import__("json").loads(row["report_json"])["fee"] for row in replayed] == ["0.12", "0.24"]


def test_sqlite_busy_timeout_does_not_partially_settle_and_retry_after_unlock_succeeds(tmp_path):
    store, oms, position, dedup, bridge = _prepared(tmp_path)
    store.timeout_seconds = 0.05
    lock = sqlite3.connect(store.path, timeout=1, isolation_level=None)
    lock.execute("BEGIN IMMEDIATE")
    report = _fill(execution_id="busy-timeout-fill", quantity=1, remaining=2)
    try:
        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            bridge.settle(report)
        assert not store.has_execution("busy-timeout-fill")
        assert oms.get("client-1").filled_quantity == 0
        assert position.qty == 0
        assert not dedup.contains("busy-timeout-fill")
    finally:
        lock.rollback()
        lock.close()

    settled = bridge.settle(report)
    assert settled.filled_quantity == 1
    assert position.qty == 1
    assert [row["execution_id"] for row in store.load_execution_journal_records()] == ["busy-timeout-fill"]


def test_concurrent_identical_execution_commits_serialize_to_one_journal_row(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    database = tmp_path / "concurrent-writers.sqlite3"
    stores = (SQLiteSettlementStore(database), SQLiteSettlementStore(database))
    barrier = Barrier(2)
    payload = {
        "execution_id": "concurrent-same-fill",
        "client_order_id": "concurrent-order",
        "filled_quantity": 1,
        "execution_price": "12.50",
    }
    order_state = {"client_order_id": "concurrent-order", "filled_quantity": 1}
    position_state = {"instrument_id": "CONCURRENT-FUT", "side": "LONG", "qty": 1, "avg_price": "12.50"}

    def commit(store):
        barrier.wait(timeout=2)
        return store.commit_fill(
            execution_id="concurrent-same-fill",
            client_order_id="concurrent-order",
            broker_order_id="concurrent-broker",
            report_payload=payload,
            order_state_payload=order_state,
            position_payload=position_state,
            instrument_id="CONCURRENT-FUT",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(commit, stores))

    assert sorted(results) == [False, True]
    assert len(stores[0].load_execution_journal_records()) == 1
    assert stores[0].load_order_state_payloads() == (order_state,)
    assert stores[0].load_position_state("CONCURRENT-FUT") == position_state


def test_safe_retry_policy_rechecks_journal_then_replays_or_preserves_conflict(tmp_path):
    from dataclasses import replace

    store, oms, position, dedup, bridge = _prepared(tmp_path)
    report = _fill(execution_id="safe-retry-fill", quantity=1, remaining=2)
    lock = sqlite3.connect(store.path, timeout=1, isolation_level=None)
    lock.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            bridge.settle(report)
        assert not store.has_execution("safe-retry-fill")
        assert oms.get("client-1").filled_quantity == 0
        assert position.qty == 0
    finally:
        lock.rollback()
        lock.close()

    # Re-read durable state before retry: no committed row means the same report may be retried.
    reopened = SQLiteSettlementStore(tmp_path / "settlement.sqlite3")
    assert not reopened.has_execution("safe-retry-fill")
    settled = bridge.settle(report)
    assert settled.filled_quantity == 1
    assert len(store.load_execution_journal_records()) == 1

    # A later caller retry after an ambiguous response must replay the durable event, not apply it twice.
    restarted_oms = OrderStateMachine(persistence_store=reopened)
    restarted_oms.restore_from_store()
    restarted_position = LivePositionAggregate("FUT-1")
    restarted_position.restore_persistence_record(reopened.load_position_state("FUT-1"))
    replay_bridge = LiveExecutionPositionBridge(
        order_state_machine=restarted_oms,
        position_fill_adapter=LivePositionFillAdapter(restarted_position),
        execution_event_deduplicator=ExecutionEventDeduplicator(persistence_store=reopened),
        position_aggregate=restarted_position,
        settlement_store=reopened,
    )
    replayed = replay_bridge.settle(report)
    assert replayed.filled_quantity == 1
    assert restarted_position.qty == 1
    assert len(reopened.load_execution_journal_records()) == 1

    # Same ID with a changed payload is a conflict, never a retry candidate.
    conflicting = replace(report, execution_price=Decimal("14.80"))
    with pytest.raises(SettlementStoreError, match="EXECUTION_ID_COLLISION"):
        replay_bridge.settle(conflicting)
    assert len(reopened.load_execution_journal_records()) == 1
    assert reopened.execution_journal_conflict_history(execution_id="safe-retry-fill")
    assert restarted_oms.get("client-1").filled_quantity == 1
    assert restarted_position.qty == 1
    assert reopened.has_unresolved_reconciliation()


def test_rest_snapshot_pending_is_not_auto_resolved_by_later_matching_websocket_fills(tmp_path):
    store, oms, position, _dedup, bridge = _prepared(tmp_path)
    store.record_reconciliation_event_pending(
        event_id="REST-CCNL-SNAPSHOT|broker-1|3|14.75",
        client_order_id="client-1",
        broker_order_id="broker-1",
        event_kind="KIS_REST_CUMULATIVE_ORDER_SNAPSHOT",
        payload={
            "cumulative_filled_quantity": 3,
            "source_authority": "SYNTHETIC_REST_ORDER_LEVEL_SNAPSHOT",
            "execution_journal_commit": False,
            "position_mutation": False,
        },
    )

    bridge.settle(_fill(execution_id="SYNTHETIC:WS-FILL-1", quantity=1, remaining=2))
    bridge.settle(_fill(execution_id="SYNTHETIC:WS-FILL-2", quantity=1, remaining=1))
    bridge.settle(_fill(
        execution_id="SYNTHETIC:WS-FILL-3", quantity=1, remaining=0, status="FILLED"
    ))

    pending = store.open_reconciliation_events(scope_key="client-1")
    assert oms.get("client-1").filled_quantity == 3
    assert position.qty == 3
    assert len(store.load_execution_journal_records()) == 3
    assert len(pending) == 1
    assert pending[0]["status"] == "PENDING"
    assert store.has_unresolved_reconciliation()

    # Characterization only: automatic cross-source resolution has no approved contract.
