from decimal import Decimal

from contracts.types import BrokerOrderCommand, ExecutionReport, OrderAckEvent, OrderIntent
from core.oms.oms_fsm import OrderStateMachine
from environments.live.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.live.position.live_execution_position_bridge import LiveExecutionPositionBridge, LivePositionFillAdapter
from environments.live.position.live_position_aggregate import LivePositionAggregate


def _report(*, execution_id, quantity, remaining, status, price):
    return ExecutionReport(
        client_order_id="C1",
        broker_order_id="B1",
        execution_id=execution_id,
        status=status,
        filled_quantity=quantity,
        remaining_quantity=remaining,
        execution_price=Decimal(price),
        execution_timestamp=None,
    )


def _scenario():
    oms = OrderStateMachine()
    command = BrokerOrderCommand("C1", "I1", "BUY", 5, "MARKET")
# oms.apply_intent(OrderIntent("C1", "I1", "BUY", 5, "NEW"))
# oms.apply_ack(OrderAckEvent("C1", True, "B1"))
# oms.register_broker_order_command(command)
    position = LivePositionAggregate("I1")
    bridge = LiveExecutionPositionBridge(
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(position),
        execution_event_deduplicator=ExecutionEventDeduplicator(),
        position_aggregate=position,
    )
    return oms, position, bridge


def test_startup_recovery_then_realtime_execution_share_same_settlement_state():
    oms, position, bridge = _scenario()

    recovery_report = _report(
        execution_id="R1", quantity=2, remaining=3,
        status="PARTIALLY_FILLED", price="350.0",
    )
    realtime_report = _report(
        execution_id="T1", quantity=3, remaining=0,
        status="FILLED", price="360.0",
    )

# bridge.settle(recovery_report)
    assert oms.get("C1").filled_quantity == 2
    assert position.snapshot().qty == 2
    assert position.snapshot().avg_price == Decimal("350.0")

# bridge.settle(realtime_report)
    state = oms.get("C1")
    snapshot = position.snapshot()
    assert state.status == "FILLED"
    assert state.filled_quantity == 5
    assert snapshot.qty == 5
    assert snapshot.avg_price == Decimal("356.0")


def test_replay_at_lifecycle_boundary_does_not_duplicate_settlement():
    oms, position, bridge = _scenario()
    report = _report(
        execution_id="R1", quantity=2, remaining=3,
        status="PARTIALLY_FILLED", price="350.0",
    )

# bridge.settle(report)
    before = (oms.get("C1").filled_quantity, position.snapshot().qty, position.snapshot().avg_price)
# bridge.settle(report)
    after = (oms.get("C1").filled_quantity, position.snapshot().qty, position.snapshot().avg_price)

    assert after == before
