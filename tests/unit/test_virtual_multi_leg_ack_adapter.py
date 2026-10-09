from types import SimpleNamespace

from application.composition.virtual_multi_leg_execution import _AckAdapter


class _Broker:
    def __init__(self, reports):
        self._reports = iter(reports)

    def submit(self, command):
        return next(self._reports)


def test_pending_orders_without_execution_ids_get_unique_broker_ids():
    broker = _Broker([
        SimpleNamespace(status="NEW", execution_id=None, broker_order_id=None),
        SimpleNamespace(status="NEW", execution_id=None, broker_order_id=None),
    ])
    adapter = _AckAdapter(broker)
    first = adapter.submit(SimpleNamespace(client_order_id="run-leg-1"))
    second = adapter.submit(SimpleNamespace(client_order_id="run-leg-2"))
    assert first.accepted is True
    assert second.accepted is True
    assert first.broker_order_id == "VIRTUAL-ORDER-run-leg-1"
    assert second.broker_order_id == "VIRTUAL-ORDER-run-leg-2"
    assert first.broker_order_id != second.broker_order_id


def test_rejected_report_is_not_acknowledged_as_accepted():
    broker = _Broker([
        SimpleNamespace(status="REJECTED", execution_id=None, broker_order_id=None, rejected_reason="NO_MARGIN"),
    ])
    response = _AckAdapter(broker).submit(SimpleNamespace(client_order_id="run-leg-rejected"))
    assert response.accepted is False
    assert response.broker_order_id is None
    assert response.broker_code == "REJECTED"
    assert response.message == "NO_MARGIN"
