"""KIS-like Standard Broker API facade for the Virtual environment."""
from __future__ import annotations

from typing import Any, Callable

from contracts.types import BrokerOrderCommand, ExecutionReport
from environments.virtual.broker.virtual_broker import VirtualBroker


class VirtualBrokerApi:
    """Option Program-facing API; hides Virtual Exchange/VSSF implementation details."""

    def __init__(self, broker: VirtualBroker, account: Any):
        self._broker = broker
        self._account = account
        self._group_snapshot_reader: Callable[[str], Any] | None = None
        self._group_reports_reader: Callable[[str], tuple[ExecutionReport, ...]] | None = None
        self._group_ids_reader: Callable[[], tuple[str, ...]] | None = None

    def attach_group_read_model(self, *, snapshot_reader, reports_reader=None, group_ids_reader=None) -> None:
        """Attach the authoritative Multi-Leg group read model at the Broker API boundary."""
        if not callable(snapshot_reader):
            raise ValueError("VIRTUAL_BROKER_GROUP_SNAPSHOT_READER_REQUIRED")
        if reports_reader is not None and not callable(reports_reader):
            raise ValueError("VIRTUAL_BROKER_GROUP_REPORTS_READER_INVALID")
        if group_ids_reader is not None and not callable(group_ids_reader):
            raise ValueError("VIRTUAL_BROKER_GROUP_IDS_READER_INVALID")
        self._group_snapshot_reader = snapshot_reader
        self._group_reports_reader = reports_reader
        self._group_ids_reader = group_ids_reader

    def get_market_snapshot(self) -> dict:
        return self._broker.get_market_snapshot()

    def get_option_quote(self, *, option_type: str, strike: float, expiry: str) -> dict | None:
        return self._broker.get_option_quote(option_type=option_type, strike=strike, expiry=expiry)

    def get_account_snapshot(self) -> Any:
        return self._account.snapshot() if hasattr(self._account, "snapshot") else self._account

    def get_position_snapshot(self) -> Any:
        position = getattr(self._broker.execution_engine, "position", None)
        if position is None:
            raise RuntimeError("VIRTUAL_BROKER_POSITION_SNAPSHOT_UNAVAILABLE")
        snapshot = getattr(position, "snapshot", None)
        if not callable(snapshot):
            raise RuntimeError("VIRTUAL_BROKER_POSITION_SNAPSHOT_UNAVAILABLE")
        return snapshot()

    def get_margin_state(self) -> dict:
        snapshot = self.get_account_snapshot()
        balances = getattr(snapshot, "balances", None)
        if not hasattr(balances, "get"):
            raise RuntimeError("VIRTUAL_BROKER_ACCOUNT_BALANCES_UNAVAILABLE")
        return {"margin_used": balances.get("margin_used"), "available_cash": balances.get("available_cash")}

    def get_group_ids(self) -> tuple[str, ...]:
        if self._group_ids_reader is None:
            raise RuntimeError("VIRTUAL_BROKER_GROUP_IDS_READ_MODEL_UNAVAILABLE")
        return tuple(self._group_ids_reader())

    def get_group_position_snapshot(self, group_id: str) -> Any:
        if self._group_snapshot_reader is None:
            raise RuntimeError("VIRTUAL_BROKER_GROUP_POSITION_READ_MODEL_UNAVAILABLE")
        snapshot = self._group_snapshot_reader(str(group_id))
        if snapshot is None:
            raise KeyError(str(group_id))
        return snapshot

    def get_group_reports(self, group_id: str) -> tuple[ExecutionReport, ...]:
        if self._group_reports_reader is None:
            raise RuntimeError("VIRTUAL_BROKER_GROUP_REPORT_READ_MODEL_UNAVAILABLE")
        return tuple(self._group_reports_reader(str(group_id)))

    def get_pnl_state(self) -> dict:
        snapshot = self.get_account_snapshot()
        balances = getattr(snapshot, "balances", None)
        if not hasattr(balances, "get"):
            raise RuntimeError("VIRTUAL_BROKER_ACCOUNT_BALANCES_UNAVAILABLE")
        return {"realized_pnl": balances.get("realized_pnl"), "unrealized_pnl": balances.get("unrealized_pnl")}
    def submit_order(self, command: BrokerOrderCommand) -> ExecutionReport:
        return self._broker.submit(command)

    def cancel_order(self, order_id: str) -> ExecutionReport:
        return self._broker.cancel(order_id)

    def query_order(self, order_id: str) -> ExecutionReport | None:
        return self._broker.query(order_id)
