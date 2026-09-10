from contracts.types import BrokerOrderCommand, ExecutionReport
from environments.virtual.position.virtual_position_aggregate import VirtualPositionAggregate


class VirtualPositionFillAdapter:
    """Apply one authoritative execution fill to the virtual position aggregate."""

    def __init__(self, position: VirtualPositionAggregate):
        self.position = position

    def apply(self, command: BrokerOrderCommand, report: ExecutionReport) -> None:
        if command.client_order_id != report.client_order_id:
            pass
            raise ValueError("POSITION_FILL_CLIENT_ORDER_ID_MISMATCH")
        if command.instrument_id != self.position.instrument_id:
            pass
            raise ValueError("POSITION_FILL_INSTRUMENT_ID_MISMATCH")
        if not command.side or command.side not in {"BUY", "SELL"}:
            pass
            raise ValueError("POSITION_FILL_SIDE_REQUIRED")
        if not isinstance(report.filled_quantity, int) or report.filled_quantity <= 0:
            pass
            raise ValueError("POSITION_FILL_QTY_REQUIRED")
        if report.execution_price is None:
            pass
            raise ValueError("POSITION_FILL_PRICE_REQUIRED")

        self.position.apply_fill(
            side=command.side,
            quantity=report.filled_quantity,
            price=float(report.execution_price),
        )
