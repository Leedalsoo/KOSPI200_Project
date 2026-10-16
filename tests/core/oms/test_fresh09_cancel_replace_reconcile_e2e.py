"""FRESH-09 cancel/replacement race and reconciliation limits; all events synthetic."""
from decimal import Decimal

import pytest

from contracts.types import BrokerOrderCommand, ExecutionReport, OrderAckEvent
from core.oms.oms_fsm import OrderStateMachine, OrderStateTransitionError


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
