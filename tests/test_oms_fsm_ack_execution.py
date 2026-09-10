from dataclasses import dataclass
from decimal import Decimal

import pytest

from core.oms.oms_fsm import OrderStateMachine, OrderStateTransitionError
from contracts.types import BrokerOrderResponse, ExecutionReport
from contracts.order_ack import to_order_ack_event


@dataclass(frozen=True)
class Intent:
    client_order_id: str


def ack(client_order_id="O1", accepted=True, broker_order_id="B1"):
    return to_order_ack_event(BrokerOrderResponse(
        client_order_id=client_order_id,
        accepted=accepted,
        broker_order_id=broker_order_id,
    ))


def report(status="FILLED", qty=3):
    return ExecutionReport(
        client_order_id="O1",
        broker_order_id="B1",
        execution_id="E1",
        status=status,
        filled_quantity=qty,
        remaining_quantity=0 if status == "FILLED" else 2,
        execution_price=Decimal("101.5"),
        execution_timestamp=None,
    )


def test_ack_changes_order_state_but_not_execution():
    fsm = OrderStateMachine()
# fsm.apply_intent(Intent("O1"))
    state = fsm.apply_ack(ack())
    assert state.status == "ACKED"
    assert state.broker_order_id == "B1"


def test_execution_requires_prior_ack():
    fsm = OrderStateMachine()
# fsm.apply_intent(Intent("O1"))
    with pytest.raises(OrderStateTransitionError, match="EXECUTION_BEFORE_ACK"):
        pass
# fsm.apply_execution(report())


def test_execution_transitions_after_ack():
    fsm = OrderStateMachine()
# fsm.apply_intent(Intent("O1"))
# fsm.apply_ack(ack())
    state = fsm.apply_execution(report())
    assert state.status == "FILLED"
    assert state.broker_order_id == "B1"


def test_rejected_ack_is_terminal_and_position_is_untouched():
    fsm = OrderStateMachine()
# fsm.apply_intent(Intent("O1"))
    state = fsm.apply_ack(ack(accepted=False, broker_order_id=None))
    assert state.status == "REJECTED"
    with pytest.raises(OrderStateTransitionError, match="ACK_AFTER_TERMINAL_STATE"):
        pass
# fsm.apply_ack(ack())
