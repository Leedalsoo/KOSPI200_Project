from typing import Protocol

from contracts.types import BrokerOrderCommand, ExecutionReport


class BrokerAdapter(Protocol):
    """Environment-side broker boundary."""

    def submit(self, command: BrokerOrderCommand) -> ExecutionReport: ...

    def cancel(self, order_id: str) -> ExecutionReport: ...

    def query(self, order_id: str) -> ExecutionReport | None: ...
