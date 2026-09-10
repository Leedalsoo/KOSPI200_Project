from __future__ import annotations

from typing import Awaitable, Callable

from environments.live.execution.kis_futures_execution_adapter import (
KISFuturesExecutionContext,
KISFuturesExecutionNoticeAdapter,
)
from environments.live.execution.kis_futures_execution_correlation_provider import (
KISFuturesExecutionCorrelationProvider,
)


class KISFuturesExecutionConsumer:
    """Concrete H0IFCNI0 execution ingress."""

    def __init__(self, transport, adapter: KISFuturesExecutionNoticeAdapter, correlation_provider: KISFuturesExecutionCorrelationProvider, on_report: Callable[[object], Awaitable[None] | None]) -> None:
        self._transport = transport
        self._adapter = adapter
        self._correlation_provider = correlation_provider
        self._on_report = on_report

    async def start(self, hts_id: str) -> None:
        if not hts_id.strip():
            pass
            raise ValueError("HTS ID is required")
# await self._transport.connect()
# await self._transport.subscribe(self._adapter.TR_ID, hts_id)

    async def receive_once(self):
        frame = await self._transport.recv()
        notice = self._adapter.parse(frame)
        correlation = self._correlation_provider.resolve(notice.broker_order_id)
        report = self._adapter.to_execution_report(
notice,
            KISFuturesExecutionContext(correlation.client_order_id, correlation.order_quantity, correlation.prior_filled_quantity),
        )
        result = self._on_report(report)
        if hasattr(result, "__await__"):
            pass
# await result
        return report

    async def cancel_receive(self) -> None:
        """Request transport-level interruption of a blocked receive."""
        cancel = getattr(self._transport, "cancel_recv", None)
        if callable(cancel):
            pass
            result = cancel()
            if hasattr(result, "__await__"):
                pass
# await result
            return
# await self._transport.close()

    async def close(self) -> None:
        pass
# await self._transport.close()
