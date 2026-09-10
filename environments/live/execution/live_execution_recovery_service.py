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


@dataclass
class LiveExecutionRecoveryService:
    """Application-owned reconciliation entry for REST recovery reports."""

    transport: RecoveryTransport
    adapter: KISFuturesExecutionRecoveryAdapter
    correlation_provider: ExecutionCorrelationProvider
    on_report: Callable[[ExecutionReport], object]

    def recover(self, query: KISExecutionRecoveryQuery) -> tuple[object, ...]:
        response = self.transport.inquire(query)

        def context_for_order(broker_order_id: str) -> KISExecutionRecoveryContext:
            correlation = self.correlation_provider.resolve(broker_order_id)
            return KISExecutionRecoveryContext(
                client_order_id=correlation.client_order_id,
                order_quantity=correlation.order_quantity,
                prior_filled_quantity=correlation.prior_filled_quantity,
                prior_average_price=getattr(correlation, "prior_average_price", None),
            )

        reports = self.adapter.normalize(response, context_for_order)
        return tuple(self.on_report(report) for report in reports)
