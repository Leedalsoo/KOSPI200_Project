"""FRESH-09 deterministic offline OMS transition tests; no broker/API is contacted."""
from decimal import Decimal

import pytest

from contracts.types import BrokerOrderCommand, ExecutionReport, OrderAckEvent
from core.oms.oms_fsm import OrderStateMachine, OrderStateTransitionError


def _command():
    return BrokerOrderCommand(
        client_order_id="fresh09-order", instrument_id="OPT-1", side="BUY",
        quantity=3, order_type="LIMIT", broker_symbol="A12345",
        strategy_id="S1",
    )


def _report(status, filled, remaining, *, price=Decimal("10"), broker_id="broker-1"):
    return ExecutionReport(
        client_order_id="fresh09-order", broker_order_id=broker_id,
        execution_id=f"exec-{filled}-{remaining}-{status}", status=status,
        filled_quantity=filled, remaining_quantity=remaining,
        execution_price=price, execution_timestamp=None,
        rejected_reason=None,
    )


def test_fresh09_partial_fill_then_cancel_preserves_filled_quantity_and_rejects_late_fill():
    # ASSUMPTION: the event objects model a deterministic broker event sequence;
    # this is OMS state-machine evidence, not a claim about KIS event ordering.
    fsm = OrderStateMachine()
    fsm.apply_intent(_command())
    fsm.register_broker_order_command(_command())
    fsm.apply_ack(OrderAckEvent(client_order_id="fresh09-order", accepted=True, broker_order_id="broker-1"))
    partial = fsm.apply_execution(_report("PARTIALLY_FILLED", 1, 2))
    assert partial.status == "PARTIALLY_FILLED"
    assert partial.filled_quantity == 1

    cancelled = fsm.apply_cancel(_report("CANCELLED", 0, 2, price=None))
    assert cancelled.status == "CANCELLED"
    assert cancelled.filled_quantity == 1

    # A late fill after terminal cancellation must not mutate the terminal OMS state.
    with pytest.raises(OrderStateTransitionError, match="EXECUTION_BEFORE_ACK"):
        fsm.apply_execution(_report("PARTIALLY_FILLED", 1, 1))
    final_state = fsm.get("fresh09-order")
    assert final_state.status == "CANCELLED"
    assert final_state.filled_quantity == 1
    assert fsm.pending_client_order_ids("S1") == ()


def test_fresh09_duplicate_or_reordered_execution_cannot_exceed_order_quantity():
    # ASSUMPTION: each ExecutionReport represents an incremental fill quantity.
    fsm = OrderStateMachine()
    fsm.apply_intent(_command())
    fsm.register_broker_order_command(_command())
    fsm.apply_ack(OrderAckEvent(client_order_id="fresh09-order", accepted=True, broker_order_id="broker-1"))
    fsm.apply_execution(_report("PARTIALLY_FILLED", 2, 1))
    with pytest.raises(OrderStateTransitionError, match="FILLED_QUANTITY_EXCEEDS_ORDER"):
        fsm.apply_execution(_report("FILLED", 2, 0))
    assert fsm.get("fresh09-order").filled_quantity == 2
