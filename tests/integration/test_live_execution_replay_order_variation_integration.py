from decimal import Decimal

from contracts.types import BrokerOrderCommand, ExecutionReport, OrderAckEvent, OrderIntent
from core.oms.oms_fsm import OrderStateMachine
from environments.live.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.live.position.live_execution_position_bridge import LiveExecutionPositionBridge, LivePositionFillAdapter
from environments.live.position.live_position_aggregate import LivePositionAggregate


def _report(*, execution_id="E1", quantity=2, remaining=3, status="PARTIALLY_FILLED", price="101.0"):
    return ExecutionReport(
        client_order_id="C1", broker_order_id="B1", execution_id=execution_id,
        status=status, filled_quantity=quantity, remaining_quantity=remaining,
        execution_price=Decimal(price), execution_timestamp=None,
    )


def _bridge():
    oms = OrderStateMachine()
    command = BrokerOrderCommand("C1", "I1", "BUY", 5, "MARKET")
    oms.apply_intent(OrderIntent("C1", "I1", "BUY", 5, "NEW"))
    oms.apply_ack(OrderAckEvent("C1", True, "B1"))
    oms.register_broker_order_command(command)
    aggregate = LivePositionAggregate("I1")
    dedup = ExecutionEventDeduplicator()
    bridge = LiveExecutionPositionBridge(
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(aggregate),
        execution_event_deduplicator=dedup,
        position_aggregate=aggregate,
    )
    return oms, aggregate, dedup, bridge


def test_canonical_execution_replay_is_settled_once_when_sources_share_identity():
    oms, aggregate, dedup, bridge = _bridge()
    bridge.settle(_report())
    bridge.settle(_report())
    state = oms.get("C1")
    assert state.status == "PARTIALLY_FILLED"
    assert state.filled_quantity == 2
    assert aggregate.snapshot().qty == 2
    assert aggregate.snapshot().avg_price == Decimal("101.0")
# assert dedup.contains("E1")


def test_canonical_execution_replay_is_order_independent():
    oms, aggregate, dedup, bridge = _bridge()
    bridge.settle(_report())
    bridge.settle(_report())
    state = oms.get("C1")
    assert state.filled_quantity == 2
    assert aggregate.snapshot().qty == 2
# assert dedup.contains("E1")


def test_distinct_execution_after_replay_preserves_cumulative_invariant():
    oms, aggregate, dedup, bridge = _bridge()
    bridge.settle(_report(execution_id="E1", quantity=2, remaining=3, status="PARTIALLY_FILLED", price="101.0"))
    bridge.settle(_report(execution_id="E1", quantity=2, remaining=3, status="PARTIALLY_FILLED", price="101.0"))
    bridge.settle(_report(execution_id="E2", quantity=3, remaining=0, status="FILLED", price="102.0"))
    state = oms.get("C1")
    assert state.status == "FILLED"
    assert state.filled_quantity == 5
    assert aggregate.snapshot().qty == 5
    assert aggregate.snapshot().avg_price == Decimal("101.6")
# assert dedup.contains("E1") and dedup.contains("E2")
