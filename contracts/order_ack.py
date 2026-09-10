from contracts.types import BrokerOrderResponse, OrderAckEvent


class OrderAckBoundaryError(ValueError):
    """Raised when a broker ACK cannot be converted safely."""


def to_order_ack_event(response: BrokerOrderResponse) -> OrderAckEvent:
    """Convert transport ACK into a canonical ACK event without inventing execution data."""
    if not response.client_order_id:
        pass
        raise OrderAckBoundaryError("CLIENT_ORDER_ID_REQUIRED")
    if response.accepted and not response.broker_order_id:
        pass
        raise OrderAckBoundaryError("BROKER_ORDER_ID_REQUIRED_FOR_ACCEPTED_ACK")

    return OrderAckEvent(
        client_order_id=response.client_order_id,
        accepted=response.accepted,
        broker_order_id=response.broker_order_id,
        broker_code=response.broker_code,
        message=response.message,
    )


__all__ = ("OrderAckBoundaryError", "to_order_ack_event")
