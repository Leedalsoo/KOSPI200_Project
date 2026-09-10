from contracts.broker import BrokerAdapter
from contracts.types import BrokerOrderCommand, ExecutionReport
from environments.virtual.execution.virtual_execution import VirtualExecutionEngine


class VirtualBroker(BrokerAdapter):
    """VSSF-derived broker boundary; no KIS/Paper/Live dependency."""

    def __init__(self, execution_engine: VirtualExecutionEngine):
        self.execution_engine = execution_engine

    def submit(self, command: BrokerOrderCommand) -> ExecutionReport:
        return self.execution_engine.execute(command)

    def cancel(self, order_id: str) -> ExecutionReport:
        return self.execution_engine.cancel(order_id)

    def query(self, order_id: str) -> ExecutionReport | None:
        return self.execution_engine.query(order_id)
