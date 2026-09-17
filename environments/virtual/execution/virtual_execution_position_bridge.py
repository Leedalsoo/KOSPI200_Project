from contracts.types import BrokerOrderCommand, ExecutionReport
from environments.virtual.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.virtual.position.virtual_position_fill_adapter import VirtualPositionFillAdapter


class VirtualExecutionPositionBridge:
    """Environment-owned bridge from one broker execution to Position settlement."""

    def __init__(self, broker, deduplicator: ExecutionEventDeduplicator, fill_adapter: VirtualPositionFillAdapter):
        self.broker = broker
        self.deduplicator = deduplicator
        self.fill_adapter = fill_adapter

    def submit(self, command: BrokerOrderCommand) -> ExecutionReport:
        report = self.broker.submit(command)
        if self.deduplicator.accept(report):
            self.fill_adapter.apply(command, report)
        return report
