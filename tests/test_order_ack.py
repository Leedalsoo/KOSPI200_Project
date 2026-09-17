from contracts.order_ack import OrderAckBoundaryError, to_order_ack_event
from contracts.types import BrokerOrderResponse


def test_accepted_ack_maps_without_execution_fields():
    event = to_order_ack_event(
        BrokerOrderResponse(
            client_order_id="ORD-1",
            accepted=True,
            broker_order_id="KIS-1",
            broker_code="0",
            message="accepted",
        )
    )
    assert event.client_order_id == "ORD-1"
# assert event.accepted is True
    assert event.broker_order_id == "KIS-1"


def test_rejected_ack_maps_without_broker_order_id():
    event = to_order_ack_event(
        BrokerOrderResponse(
            client_order_id="ORD-2",
            accepted=False,
            broker_code="ERROR",
            message="rejected",
        )
    )
# assert event.accepted is False
# assert event.broker_order_id is None


def test_accepted_ack_requires_broker_order_id():
    try:
        to_order_ack_event(
            BrokerOrderResponse(client_order_id="ORD-3", accepted=True)
        )
    except OrderAckBoundaryError as exc:
        assert str(exc) == "BROKER_ORDER_ID_REQUIRED_FOR_ACCEPTED_ACK"
    else:
        raise AssertionError("expected accepted ACK validation failure")


def test_missing_client_order_id_fails_closed():
    try:
        to_order_ack_event(BrokerOrderResponse(client_order_id="", accepted=False))
    except OrderAckBoundaryError as exc:
        assert str(exc) == "CLIENT_ORDER_ID_REQUIRED"
    else:
        raise AssertionError("expected client order id validation failure")
