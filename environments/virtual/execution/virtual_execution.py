from typing import Callable, Iterable

from contracts.execution import ExecutionProvider
from contracts.types import BrokerOrderCommand, DataQuality, ExecutionReport


class VirtualExecutionEngine(ExecutionProvider):
    """Virtual execution boundary with an explicit authoritative-fill seam.

    The environment supplies the real VSSF market-match/execution adapter.
    This class does not invent an execution price when that adapter is absent.
    """

    def __init__(
        self,
        position,
        account,
        *,
        authoritative_execute: Callable[[BrokerOrderCommand], ExecutionReport]
        | None = None,
    ):
        self.position = position
        self.account = account
        self._authoritative_execute = authoritative_execute
        self._reports: dict[str, ExecutionReport] = {}

    def execute(self, order: BrokerOrderCommand) -> ExecutionReport:
        if self._authoritative_execute is not None:
            report = self._authoritative_execute(order)
            self._reports[order.client_order_id] = report
            return report

        # A virtual execution cannot be reported as FILLED without the
        # authoritative VSSF matching/execution path. Fail closed instead of
        # manufacturing a synthetic fill report.
        raise RuntimeError("AUTHORITATIVE_VSSF_EXECUTION_ADAPTER_REQUIRED")

    def cancel(self, client_order_id: str) -> ExecutionReport:
        report = ExecutionReport(
            client_order_id=client_order_id,
            broker_order_id=client_order_id,
            execution_id=None,
            status="CANCELLED",
            filled_quantity=0,
            remaining_quantity=0,
            execution_price=None,
            execution_timestamp=None,
            source_freshness=DataQuality(
                is_fresh=True,
                is_complete=False,
                source_available=True,
                reason="virtual_execution_cancel_policy",
            ),
        )
        self._reports[client_order_id] = report
        return report

    def query(self, client_order_id: str) -> ExecutionReport | None:
        return self._reports.get(client_order_id)

    def reports(self) -> Iterable[ExecutionReport]:
        return tuple(self._reports.values())

    def query_execution(self, execution_id: str) -> ExecutionReport | None:
        for report in self._reports.values():
            if report.execution_id == execution_id:
                return report
        return None
