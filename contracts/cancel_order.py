from dataclasses import dataclass


@dataclass(frozen=True)
class CancelPendingOrdersRequest:
    """OMS cancellation command containing only authoritative pending order IDs."""

    signal_id: str
    strategy_id: str
    client_order_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.signal_id.strip():
            raise ValueError("CANCEL_SIGNAL_ID_REQUIRED")
        if not self.strategy_id.strip():
            raise ValueError("CANCEL_STRATEGY_ID_REQUIRED")
        if any(not str(order_id).strip() for order_id in self.client_order_ids):
            raise ValueError("CANCEL_CLIENT_ORDER_ID_REQUIRED")


__all__ = ("CancelPendingOrdersRequest",)
