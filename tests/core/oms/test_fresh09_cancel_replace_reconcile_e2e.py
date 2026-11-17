"""FRESH-09 cancel/replacement race and reconciliation limits; all events synthetic."""
from decimal import Decimal

import pytest

from contracts.types import BrokerOrderCommand, ExecutionReport, OrderAckEvent
from core.oms.oms_fsm import OrderStateMachine, OrderStateTransitionError
from datetime import datetime, timezone
import hashlib
import json

from application.composition.track2_u19_recovery import ValidationOnlyTrack2U19RecoveryCoordinator
from core.oms.track2_u19_recovery import (
    U19BrokerPositionSnapshot,
    U19ExecutionEvent,
    U19ExecutionLedgerSnapshot,
    U19Position,
    U19RecoveryStatus,
)
from environments.virtual.position.track2_u19_recovery_store import SqliteTrack2U19RecoveryStore


def _command(client_id, quantity=3):
    return BrokerOrderCommand(client_order_id=client_id, instrument_id="OPT-1", side="BUY",
        quantity=quantity, order_type="LIMIT", broker_symbol="A12345", strategy_id="S1")


def _report(client_id, broker_id, status, fill, remaining, execution_id, price=Decimal("10")):
    return ExecutionReport(client_order_id=client_id, broker_order_id=broker_id, execution_id=execution_id,
        status=status, filled_quantity=fill, remaining_quantity=remaining, execution_price=price,
        execution_timestamp=None, rejected_reason=None)


def _register_ack(fsm, command, broker_id):
    fsm.apply_intent(command)
    fsm.register_broker_order_command(command)
    fsm.apply_ack(OrderAckEvent(client_order_id=command.client_order_id, accepted=True, broker_order_id=broker_id))


def test_fresh09_partial_cancel_late_fill_racing_replacement_and_synthetic_position_reconcile():
    # ASSUMPTION: event ordering and position ledger below are synthetic fixtures,
    # not a claim about KIS ordering or a production reconciliation integration.
    fsm = OrderStateMachine()
    old = _command("old-order")
    _register_ack(fsm, old, "broker-old")
    accepted_execution_ids = set()
    synthetic_position_quantity = 0

    first_fill = _report("old-order", "broker-old", "PARTIALLY_FILLED", 1, 2, "exec-old-1")
    state = fsm.apply_execution(first_fill)
    accepted_execution_ids.add(first_fill.execution_id)
    synthetic_position_quantity += first_fill.filled_quantity
    assert state.filled_quantity == 1

    cancelled = fsm.apply_cancel(_report("old-order", "broker-old", "CANCELLED", 0, 2, "cancel-old", price=None))
    assert cancelled.status == "CANCELLED" and cancelled.filled_quantity == 1

    # Replacement is a separate OMS order; no production replacement orchestrator is assumed.
    replacement = _command("replacement-order", quantity=2)
    _register_ack(fsm, replacement, "broker-replacement")
    replacement_fill = _report("replacement-order", "broker-replacement", "PARTIALLY_FILLED", 1, 1, "exec-replacement-1")
    replacement_state = fsm.apply_execution(replacement_fill)
    accepted_execution_ids.add(replacement_fill.execution_id)
    synthetic_position_quantity += replacement_fill.filled_quantity
    assert replacement_state.filled_quantity == 1

    # A late execution against the cancelled original must not change OMS or ledger.
    late_fill = _report("old-order", "broker-old", "PARTIALLY_FILLED", 1, 1, "exec-old-late")
    with pytest.raises(OrderStateTransitionError):
        fsm.apply_execution(late_fill)
    assert fsm.get("old-order").status == "CANCELLED"
    assert fsm.get("old-order").filled_quantity == 1
    assert synthetic_position_quantity == 2
    assert len(accepted_execution_ids) == 2

    # The ledger here is deliberately synthetic; this does not prove production lot-store integration.
    accepted_oms_fills = fsm.get("old-order").filled_quantity + fsm.get("replacement-order").filled_quantity
    assert accepted_oms_fills == synthetic_position_quantity


def test_fresh09_oms_has_no_restart_restore_contract_to_assert_as_pass():
    # Explicit scope marker: the current FSM exposes no persistence/restore API.
    fsm = OrderStateMachine()
    assert not any(callable(getattr(fsm, name, None)) for name in ("save_state", "restore_state", "load_state", "from_snapshot"))



def test_fresh09_replace_cancel_late_fill_lineage_gates_u19_checkpoint(tmp_path):
    # Validation-only lineage fixture; IDs and event ordering are synthetic, not KIS schema claims.
    fsm = OrderStateMachine()
    old = _command("client-old", quantity=3)
    _register_ack(fsm, old, "broker-old")
    first = _report("client-old", "broker-old", "PARTIALLY_FILLED", 1, 2, "exec-old-1")
    fsm.apply_execution(first)

    cancel_id = "cancel-request-old-1"
    cancelled = fsm.apply_cancel(
        _report("client-old", "broker-old", "CANCELLED", 0, 2, cancel_id, price=None)
    )
    assert cancelled.status == "CANCELLED"
    assert cancelled.filled_quantity == 1

    replacement = _command("client-replacement", quantity=2)
    _register_ack(fsm, replacement, "broker-replacement")
    replacement_fill = _report(
        "client-replacement", "broker-replacement",
        "PARTIALLY_FILLED", 1, 1, "exec-replacement-1",
    )
    fsm.apply_execution(replacement_fill)

    # A late fill after cancel ACK is not accepted by the current FSM terminal-state transition.
    late_fill = _report(
        "client-old", "broker-old", "PARTIALLY_FILLED", 1, 1, "exec-old-late",
    )
    with pytest.raises(OrderStateTransitionError):
        fsm.apply_execution(late_fill)

    lineage = {
        "old": {
            "client_order_id": "client-old",
            "broker_order_id": "broker-old",
            "cancel_event_id": cancel_id,
            "execution_ids": ["exec-old-1", "exec-old-late"],
        },
        "replacement": {
            "client_order_id": "client-replacement",
            "broker_order_id": "broker-replacement",
            "replaces_client_order_id": "client-old",
            "execution_ids": ["exec-replacement-1"],
        },
    }
    assert lineage["replacement"]["replaces_client_order_id"] == lineage["old"]["client_order_id"]

    def fingerprint(record):
        payload = json.dumps(record, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    events = (
        U19ExecutionEvent("exec-old-1", fingerprint({
            "client_order_id": "client-old", "broker_order_id": "broker-old",
            "cancel_event_id": cancel_id, "quantity": 1, "status": "PARTIALLY_FILLED",
        })),
        U19ExecutionEvent("exec-replacement-1", fingerprint({
            "client_order_id": "client-replacement", "broker_order_id": "broker-replacement",
            "replaces_client_order_id": "client-old", "quantity": 1,
        })),
        U19ExecutionEvent("exec-old-late", fingerprint({
            "client_order_id": "client-old", "broker_order_id": "broker-old",
            "cancel_event_id": cancel_id, "quantity": 1, "status": "LATE_FILL_RECONCILED",
        })),
    )
    as_of = datetime(2026, 11, 18, 1, 0, tzinfo=timezone.utc)
    group_id = "validation-fresh09-replace-cancel-late-fill"
    instrument_id = "SYNTHETIC_CONTRACT:FRESH09:OPT-1"

    def snapshots(quantity, *, pending, snapshot_suffix):
        positions = (U19Position(instrument_id, Decimal(str(quantity))),) if quantity else ()
        broker_payload = {
            "group_id": group_id,
            "positions": [(p.instrument_id, str(p.signed_quantity)) for p in positions],
        }
        ledger_payload = {
            **broker_payload,
            "events": [(e.execution_id, e.fingerprint) for e in events],
            "pending": list(pending),
        }
        digest = lambda value: hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        broker_snapshot = U19BrokerPositionSnapshot(
            group_id, "broker-" + snapshot_suffix, as_of,
            "VALIDATION_ONLY:BROKER_EXCHANGE", positions, True, True,
            digest(broker_payload),
        )
        ledger_snapshot = U19ExecutionLedgerSnapshot(
            group_id, "ledger-" + snapshot_suffix, as_of,
            "VALIDATION_ONLY:EXECUTION_LEDGER", positions, True,
            digest(ledger_payload), events, tuple(pending),
        )
        return broker_snapshot, ledger_snapshot

    store_path = tmp_path / "fresh09-u19.sqlite3"
    coordinator = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(store_path)
    )

    # Cancel acknowledgement is not sufficient: the old broker order remains unresolved for late-fill purposes.
    broker_pending, ledger_pending = snapshots(2, pending=("broker-old",), snapshot_suffix="pending")
    pending_decision = coordinator.recover(
        group_id=group_id, broker_snapshot=broker_pending, ledger_snapshot=ledger_pending
    )
    assert pending_decision.status is U19RecoveryStatus.PENDING_ORDER_RECONCILIATION_REQUIRED
    assert pending_decision.pending_order_ids == ("broker-old",)
    assert pending_decision.restore_allowed is False

    # Alternative validation fixture supplies the late fill and reconciles broker/ledger aggregate quantity.
    # 1 old initial + 1 old late fill + 1 replacement fill = 3.
    broker_final, ledger_final = snapshots(3, pending=(), snapshot_suffix="reconciled")
    final_decision = coordinator.recover(
        group_id=group_id, broker_snapshot=broker_final, ledger_snapshot=ledger_final
    )
    assert final_decision.status is U19RecoveryStatus.RESTORE_ALLOWED
    assert final_decision.positions == (U19Position(instrument_id, Decimal("3")),)
    assert {event.execution_id for event in final_decision.execution_events} == {
        "exec-old-1", "exec-old-late", "exec-replacement-1",
    }
    assert final_decision.pending_order_ids == ()
    assert final_decision.new_entry_enabled is False
    assert final_decision.order_submission_enabled is False

    checkpoint = SqliteTrack2U19RecoveryStore(store_path).load_latest(group_id)
    assert checkpoint["status"] == U19RecoveryStatus.RESTORE_ALLOWED.value
    assert checkpoint["positions"] == [
        {"instrument_id": instrument_id, "signed_quantity": "3"}
    ]
    assert checkpoint["pending_order_ids"] == []
