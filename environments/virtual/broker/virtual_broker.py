from contracts.broker import BrokerAdapter
from contracts.types import BrokerOrderCommand, ExecutionReport
from environments.virtual.execution.virtual_execution import VirtualExecutionEngine


class VirtualBroker(BrokerAdapter):
    """KIS-like broker boundary fed by the Virtual Exchange market source."""

    def __init__(self, execution_engine: VirtualExecutionEngine, *, market_data_handler=None):
        self.execution_engine = execution_engine
        self._market_data_handler = market_data_handler
        self._last_market_tick = None
        self._option_quotes = {}

    def process_market_data(self, tick, *, option_quotes=None) -> None:
        handler = self._market_data_handler
        if not callable(handler):
            raise RuntimeError("VIRTUAL_BROKER_MARKET_DATA_HANDLER_REQUIRED")
        self._last_market_tick = tick
        self._option_quotes = dict(option_quotes or {})
        handler(tick)

    def get_market_snapshot(self) -> dict:
        if self._last_market_tick is None:
            raise RuntimeError("VIRTUAL_BROKER_MARKET_DATA_UNAVAILABLE")
        return {
            "source": "VirtualBroker",
            "tick": self._last_market_tick,
            "option_quotes": dict(self._option_quotes),
        }

    def get_option_quote(self, *, option_type: str, strike: float, expiry: str) -> dict | None:
        return self._option_quotes.get((option_type.upper(), float(strike), expiry))

    def submit(self, command: BrokerOrderCommand) -> ExecutionReport:
        return self.execution_engine.execute(command)

    def cancel(self, order_id: str) -> ExecutionReport:
        return self.execution_engine.cancel(order_id)

    def query(self, order_id: str) -> ExecutionReport | None:
        return self.execution_engine.query(order_id)
