from contracts.broker import BrokerAdapter
from contracts.types import BrokerOrderCommand, ExecutionReport
from environments.virtual.execution.virtual_execution import VirtualExecutionEngine


class VirtualBroker(BrokerAdapter):
    """VSSF-derived broker boundary; no KIS/Paper/Live dependency."""

    def __init__(self, execution_engine: VirtualExecutionEngine, *, market_data_handler=None):
        self.execution_engine = execution_engine
        self._market_data_handler = market_data_handler

    def process_market_data(self, tick) -> None:
        handler = self._market_data_handler
        if not callable(handler):
            raise RuntimeError("VIRTUAL_BROKER_MARKET_DATA_HANDLER_REQUIRED")
        handler(tick)

    def submit(self, command: BrokerOrderCommand) -> ExecutionReport:
        return self.execution_engine.execute(command)

    def cancel(self, order_id: str) -> ExecutionReport:
        return self.execution_engine.cancel(order_id)

    def query(self, order_id: str) -> ExecutionReport | None:
        return self.execution_engine.query(order_id)
