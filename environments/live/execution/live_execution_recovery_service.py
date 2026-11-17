from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from contracts.types import ExecutionReport
from environments.live.execution.kis_futures_execution_recovery_adapter import (
KISExecutionRecoveryContext,
KISExecutionRecoveryQuery,
KISFuturesExecutionRecoveryAdapter,
)


class RecoveryTransport(Protocol):
    def inquire(self, query: KISExecutionRecoveryQuery) -> dict[str, object]: ...


class ExecutionCorrelationProvider(Protocol):
    def resolve(self, broker_order_id: str): ...


class RecoveryReconciliationHandlerRequired(RuntimeError):
    """Raised when an order-level snapshot has no separate reconciliation handler."""


@dataclass
class LiveExecutionRecoveryService:
    """Application-owned reconciliation entry for REST recovery reports."""

    transport: RecoveryTransport
    adapter: KISFuturesExecutionRecoveryAdapter
    correlation_provider: ExecutionCorrelationProvider
    on_report: Callable[[ExecutionReport], object]
    on_reconciliation_required: Callable[[ExecutionReport, int], object] | None = None

    def recover(self, query: KISExecutionRecoveryQuery) -> tuple[object, ...]:
        response = self.transport.inquire(query)
        contexts: dict[str, KISExecutionRecoveryContext] = {}

        def context_for_order(broker_order_id: str) -> KISExecutionRecoveryContext:
            correlation = self.correlation_provider.resolve(broker_order_id)
            context = KISExecutionRecoveryContext(
                client_order_id=correlation.client_order_id,
                order_quantity=correlation.order_quantity,
                prior_filled_quantity=correlation.prior_filled_quantity,
                prior_average_price=getattr(correlation, "prior_average_price", None),
            )
            contexts[broker_order_id] = context
            return context

        reports = self.adapter.normalize(response, context_for_order)
        cumulative_by_order = {
            broker_id: context.prior_filled_quantity
            for broker_id, context in contexts.items()
        }
        results: list[object] = []
        for report in reports:
            broker_id = str(report.broker_order_id or "").strip()
            execution_id = str(report.execution_id or "").strip()
            if execution_id.startswith("REST-CCNL-SNAPSHOT|"):
                if self.on_reconciliation_required is None:
                    raise RecoveryReconciliationHandlerRequired(
                        "KIS_REST_ORDER_SNAPSHOT_REQUIRES_RECONCILIATION_HANDLER"
                    )
                cumulative_by_order[broker_id] = (
                    cumulative_by_order.get(broker_id, 0) + report.filled_quantity
                )
                results.append(self.on_reconciliation_required(
                    report, cumulative_by_order[broker_id]
                ))
                continue
            results.append(self.on_report(report))
        return tuple(results)
