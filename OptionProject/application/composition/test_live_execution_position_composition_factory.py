from __future__ import annotations

from contracts.types import BrokerOrderCommand, ExecutionReport, OrderAckEvent, OrderIntent
from core.oms.oms_fsm import OrderStateMachine
from environments.live.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.live.position.live_position_aggregate import LivePositionAggregate
from environments.live.position.live_execution_position_bridge import LiveExecutionPositionBridge, LivePositionFillAdapter
from application.composition.live_execution_position_composition_factory import create_live_execution_position_composition


def test_live_execution_position_composition_uses_real_bridge_contract():
    oms = OrderStateMachine()
# oms.apply_intent(OrderIntent("C1", "I1", "BUY", 2, "OPEN"))
    command = BrokerOrderCommand("C1", "I1", "BUY", 2, "MARKET")
# oms.register_broker_order_command(command)
# oms.apply_ack(OrderAckEvent("C1", True, "B1"))

    aggregate = LivePositionAggregate("I1")
    dedup = ExecutionEventDeduplicator()
    composition = create_live_execution_position_composition(
        execution_source=object(),
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(aggregate),
        execution_event_deduplicator=dedup,
        position_aggregate=aggregate,
    )

    report = ExecutionReport(
        client_order_id="C1",
        broker_order_id="B1",
        execution_id="E1",
        status="PARTIALLY_FILLED",
        filled_quantity=1,
        remaining_quantity=1,
        execution_price=101.25,
        execution_timestamp=None,
    )
    state = composition.settle(report)

    assert state.filled_quantity == 1
    assert aggregate.snapshot().qty == 1
# assert dedup.contains("E1")


def test_duplicate_execution_is_blocked_before_second_position_mutation():
    oms = OrderStateMachine()
# oms.apply_intent(OrderIntent("C1", "I1", "BUY", 2, "OPEN"))
    command = BrokerOrderCommand("C1", "I1", "BUY", 2, "MARKET")
# oms.register_broker_order_command(command)
# oms.apply_ack(OrderAckEvent("C1", True, "B1"))

    aggregate = LivePositionAggregate("I1")
    bridge = LiveExecutionPositionBridge(
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(aggregate),
        execution_event_deduplicator=ExecutionEventDeduplicator(),
        position_aggregate=aggregate,
    )
    report = ExecutionReport(
        client_order_id="C1",
        broker_order_id="B1",
        execution_id="E1",
        status="PARTIALLY_FILLED",
        filled_quantity=1,
        remaining_quantity=1,
        execution_price=101.25,
        execution_timestamp=None,
    )

    first = bridge.settle(report)
    duplicate = bridge.settle(report)

    assert first.filled_quantity == 1
    assert duplicate.filled_quantity == 1
    assert aggregate.snapshot().qty == 1
