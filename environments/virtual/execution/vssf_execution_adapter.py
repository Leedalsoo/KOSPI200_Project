from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from contracts.types import BrokerOrderCommand, DataQuality, ExecutionFill, ExecutionReport
from environments.virtual.authoritative_vssf.canonical import CanonicalExecutionReport, VSSFOrderResult


class VSSFCommandContextProvider(Protocol):
    def build_command(self, order: BrokerOrderCommand) -> object: ...


class VSSFRuntime(Protocol):
    def process_order(self, command: object) -> object: ...
    def query_order(self, client_order_id: str) -> object | None: ...
    def cancel_order(self, client_order_id: str) -> object | None: ...


@dataclass(frozen=True)
class VSSFExecutionAdapter:
    """Standard BrokerOrderCommand ↔ authoritative VSSF order lifecycle."""

    command_context: VSSFCommandContextProvider
    vssf_runtime: VSSFRuntime

    def _map(self, result: object) -> ExecutionReport:
        if isinstance(result, CanonicalExecutionReport):
            return ExecutionReport(
                client_order_id=result.client_order_id, broker_order_id=None,
                execution_id=result.exec_id, status="FILLED",
                filled_quantity=int(result.executed_qty), remaining_quantity=0,
                execution_price=result.executed_price,
                execution_timestamp=datetime.fromisoformat(result.timestamp),
                fee=Decimal(str(result.fee)),
                source_freshness=DataQuality(is_fresh=True, is_complete=True,
                    source_available=True, reason="vssf_authoritative_execution"),
            )
        if isinstance(result, VSSFOrderResult):
            return ExecutionReport(
                client_order_id=result.client_order_id, broker_order_id=result.client_order_id,
                execution_id=result.exec_id, status=result.status,
                filled_quantity=int(result.executed_qty), remaining_quantity=int(result.remaining_qty),
                execution_price=result.executed_price,
                execution_timestamp=datetime.fromisoformat(result.executed_at or result.observed_at),
                fee=(Decimal(str(result.fee)) if result.fee is not None else None),
                source_freshness=DataQuality(is_fresh=True, is_complete=result.status == "FILLED",
                    source_available=True, reason="vssf_authoritative_order_lifecycle"),
                submitted_at=datetime.fromisoformat(result.submitted_at),
                lifecycle_reason=result.lifecycle_reason,
                execution_fills=tuple(
                    ExecutionFill(
                        execution_id=fill.exec_id,
                        filled_quantity=int(fill.executed_qty),
                        execution_price=Decimal(str(fill.executed_price)),
                        execution_timestamp=datetime.fromisoformat(fill.timestamp),
                        fee=Decimal(str(fill.fee)),
                    )
                    for fill in result.execution_fills
                ),
            )
        raise RuntimeError("VSSF_ORDER_RESULT_INVALID")

    def execute(self, order: BrokerOrderCommand) -> ExecutionReport:
        result = self.vssf_runtime.process_order(self.command_context.build_command(order))
        if result is None:
            raise RuntimeError("VSSF_ORDER_NOT_ACCEPTED")
        if isinstance(result, CanonicalExecutionReport):
            lifecycle = self.vssf_runtime.query_order(result.client_order_id)
            if lifecycle is not None:
                return self._map(lifecycle)
        return self._map(result)

    def query(self, client_order_id: str) -> ExecutionReport | None:
        result = self.vssf_runtime.query_order(client_order_id)
        return None if result is None else self._map(result)

    def cancel(self, client_order_id: str) -> ExecutionReport:
        cancel_result = self.vssf_runtime.cancel_order(client_order_id)
        # Always re-query after a cancel request: the order may have filled just
        # before cancellation, or the cancel acknowledgement may not be terminal.
        confirmed = self.vssf_runtime.query_order(client_order_id)
        if confirmed is None:
            raise RuntimeError("VSSF_CANCEL_RECONCILIATION_UNAVAILABLE")
        status = str(getattr(confirmed, "status", "")).upper()
        if status not in {"CANCELLED", "FILLED", "REJECTED"}:
            raise RuntimeError("VSSF_CANCEL_TERMINAL_CONFIRMATION_REQUIRED")
        if cancel_result is None and status != "FILLED":
            raise RuntimeError("VSSF_CANCEL_REQUEST_UNCONFIRMED")
        return self._map(confirmed)
