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


class _TimeoutBroker:
    def __init__(self, query_report=None):
        self.query_report = query_report
        self.query_calls = []

    def submit(self, command):
        raise TimeoutError("transport timed out after submit")

    def query(self, client_order_id):
        self.query_calls.append(client_order_id)
        return self.query_report


def test_submit_timeout_reconciles_authoritative_order_report_before_returning():
    report = SimpleNamespace(
        status="FILLED", execution_id="EXEC-RECONCILED", broker_order_id="BROKER-1",
        rejected_reason=None,
    )
    broker = _TimeoutBroker(report)
    adapter = _AckAdapter(broker)
    command = SimpleNamespace(client_order_id="run-leg-timeout", quantity=2, group_id="g", leg_id="call")

    response = adapter.submit(command)

    assert response.accepted is True
    assert response.broker_order_id == "BROKER-1"
    assert adapter.last_report is report
    assert broker.query_calls == ["run-leg-timeout"]


def test_submit_timeout_without_query_result_is_unknown_not_rejected():
    broker = _TimeoutBroker()
    adapter = _AckAdapter(broker)
    command = SimpleNamespace(client_order_id="run-leg-unknown", quantity=3, group_id="g", leg_id="put")

    response = adapter.submit(command)

    assert response.accepted is False
    assert response.broker_code == "UNKNOWN"
    assert adapter.last_report.status == "UNKNOWN"
    assert adapter.last_report.remaining_quantity == 3
    assert adapter.last_report.rejected_reason == "VIRTUAL_ORDER_STATUS_RECONCILIATION_REQUIRED"
    assert broker.query_calls == ["run-leg-unknown"]
