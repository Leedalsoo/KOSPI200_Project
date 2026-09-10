from decimal import Decimal

from contracts.types import BrokerOrderCommand, ExecutionReport
from environments.virtual.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.virtual.execution.virtual_execution_position_bridge import VirtualExecutionPositionBridge
from environments.virtual.position.virtual_position_aggregate import VirtualPositionAggregate
from environments.virtual.position.virtual_position_fill_adapter import VirtualPositionFillAdapter


class StubBroker:
    def __init__(self, report):
        self.report = report

    def submit(self, command):
        return self.report


def command():
    return BrokerOrderCommand(
        client_order_id="o1", instrument_id="K200-C-350", side="BUY", quantity=3, order_type="LIMIT"
    )


def report(execution_id="e1"):
    return ExecutionReport(
        client_order_id="o1", broker_order_id="b1", execution_id=execution_id,
        status="FILLED", filled_quantity=3, remaining_quantity=0,
        execution_price=Decimal("101"), execution_timestamp=None,
    )


def test_one_execution_is_applied_once():
    position = VirtualPositionAggregate("K200-C-350")
    broker = StubBroker(report())
    bridge = VirtualExecutionPositionBridge(
# broker, ExecutionEventDeduplicator(), VirtualPositionFillAdapter(position)
    )
# bridge.submit(command())
# bridge.submit(command())
    assert position.snapshot()["K200-C-350"].qty == 3


def test_distinct_execution_events_are_each_applied():
    position = VirtualPositionAggregate("K200-C-350")
    broker = StubBroker(report("e1"))
    bridge = VirtualExecutionPositionBridge(
# broker, ExecutionEventDeduplicator(), VirtualPositionFillAdapter(position)
    )
# bridge.submit(command())
    broker.report = report("e2")
# bridge.submit(command())
    assert position.snapshot()["K200-C-350"].qty == 6
