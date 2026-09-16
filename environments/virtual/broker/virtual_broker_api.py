"""KIS-like Standard Broker API facade for the Virtual environment."""
from __future__ import annotations

from typing import Any

from contracts.types import BrokerOrderCommand, ExecutionReport
from environments.virtual.broker.virtual_broker import VirtualBroker


class VirtualBrokerApi:
    """Option Program-facing API; hides Virtual Exchange/VSSF implementation details."""

    def __init__(self, broker: VirtualBroker, account: Any):
        self._broker = broker
        self._account = account

    def get_market_snapshot(self) -> dict:
        return self._broker.get_market_snapshot()

    def get_option_quote(self, *, option_type: str, strike: float, expiry: str) -> dict | None:
        return self._broker.get_option_quote(option_type=option_type, strike=strike, expiry=expiry)

    def get_account_snapshot(self) -> Any:
        return self._account.snapshot() if hasattr(self._account, "snapshot") else self._account

    def submit_order(self, command: BrokerOrderCommand) -> ExecutionReport:
        return self._broker.submit(command)

    def cancel_order(self, order_id: str) -> ExecutionReport:
        return self._broker.cancel(order_id)

    def query_order(self, order_id: str) -> ExecutionReport | None:
        return self._broker.query(order_id)
