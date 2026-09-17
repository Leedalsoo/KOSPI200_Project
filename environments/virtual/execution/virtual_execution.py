from typing import Callable, Iterable

from contracts.execution import ExecutionProvider
from contracts.types import BrokerOrderCommand, DataQuality, ExecutionReport


class VirtualExecutionEngine(ExecutionProvider):
    """Virtual execution boundary with authoritative VSSF lifecycle callbacks."""

    def __init__(self, position, account, *, authoritative_execute: Callable | None = None,
                 authoritative_query: Callable | None = None, authoritative_cancel: Callable | None = None):
        self.position = position
        self.account = account
        self._authoritative_execute = authoritative_execute
        self._authoritative_query = authoritative_query
        self._authoritative_cancel = authoritative_cancel
        self._reports: dict[str, ExecutionReport] = {}

    def execute(self, order: BrokerOrderCommand) -> ExecutionReport:
        if self._authoritative_execute is None:
            raise RuntimeError("AUTHORITATIVE_VSSF_EXECUTION_ADAPTER_REQUIRED")
        report = self._authoritative_execute(order)
        self._reports[order.client_order_id] = report
        return report

    def cancel(self, client_order_id: str) -> ExecutionReport:
        if self._authoritative_cancel is not None:
            report = self._authoritative_cancel(client_order_id)
            self._reports[client_order_id] = report
            return report
        report = ExecutionReport(
            client_order_id=client_order_id, broker_order_id=client_order_id,
            execution_id=None, status="CANCELLED", filled_quantity=0,
            remaining_quantity=0, execution_price=None, execution_timestamp=None,
            source_freshness=DataQuality(is_fresh=True, is_complete=False,
                source_available=True, reason="virtual_execution_cancel_policy"),
        )
        self._reports[client_order_id] = report
        return report

    def query(self, client_order_id: str) -> ExecutionReport | None:
        if self._authoritative_query is not None:
            report = self._authoritative_query(client_order_id)
            if report is not None:
                self._reports[client_order_id] = report
                return report
        return self._reports.get(client_order_id)

    def reports(self) -> Iterable[ExecutionReport]:
        return tuple(self._reports.values())

    def query_execution(self, execution_id: str) -> ExecutionReport | None:
        for report in self._reports.values():
            if report.execution_id == execution_id:
                return report
        return None
