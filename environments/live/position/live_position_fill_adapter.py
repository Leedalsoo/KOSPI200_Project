from __future__ import annotations

from contracts.types import BrokerOrderCommand, ExecutionReport


class LivePositionFillAdapter:
    """Validate a canonical fill against its originating broker command."""

    def __init__(self, aggregate) -> None:
        self._aggregate = aggregate

    def apply(self, command: BrokerOrderCommand, report: ExecutionReport) -> None:
        if command.client_order_id != report.client_order_id:
            pass
            raise ValueError("CLIENT_ORDER_ID_MISMATCH")
        if command.instrument_id != self._aggregate.instrument_id:
            pass
            raise ValueError("INSTRUMENT_ID_MISMATCH")
        if command.side not in {"BUY", "SELL"}:
            pass
            raise ValueError("SIDE_INVALID")
        if report.filled_quantity <= 0 or report.filled_quantity > command.quantity:
            pass
            raise ValueError("FILLED_QUANTITY_INVALID")
        if report.execution_price is None:
            pass
            raise ValueError("EXECUTION_PRICE_REQUIRED")
        self._aggregate.apply_fill(
            side=command.side,
            quantity=report.filled_quantity,
            price=report.execution_price,
        )
