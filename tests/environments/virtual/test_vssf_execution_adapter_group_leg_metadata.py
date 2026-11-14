from decimal import Decimal
from types import SimpleNamespace

from environments.virtual.authoritative_vssf.canonical import VSSFOrderResult
from environments.virtual.execution.vssf_execution_adapter import VSSFExecutionAdapter


STAMP = "2026-10-22T02:16:00+09:00"


class _Context:
    def build_command(self, order):
        return order


class _Runtime:
    def __init__(self):
        self.result = VSSFOrderResult(
            client_order_id="client-1",
            status="FILLED",
            submitted_at=STAMP,
            observed_at=STAMP,
            remaining_qty=0,
            exec_id="exec-1",
            executed_qty=1,
            executed_price=Decimal("42.25"),
            fee=Decimal("0"),
            executed_at=STAMP,
        )

    def process_order(self, command):
        return self.result

    def query_order(self, client_order_id):
        assert client_order_id == "client-1"
        return self.result

    def cancel_order(self, client_order_id, *, lifecycle_reason="MANUAL"):
        assert client_order_id == "client-1"
        return self.result


def _adapter_and_order():
    adapter = VSSFExecutionAdapter(_Context(), _Runtime())
    order = SimpleNamespace(client_order_id="client-1", group_id="group-1", leg_id="leg-1")
    return adapter, order


def test_execute_propagates_group_and_leg_metadata_to_canonical_report():
    adapter, order = _adapter_and_order()

    report = adapter.execute(order)

    assert report.status == "FILLED"
    assert report.group_id == "group-1"
    assert report.leg_id == "leg-1"


def test_query_and_cancel_keep_original_group_and_leg_metadata():
    adapter, order = _adapter_and_order()
    adapter.execute(order)

    queried = adapter.query("client-1")
    cancelled = adapter.cancel("client-1", lifecycle_reason="VALIDATION_ONLY_TEST")

    assert queried is not None
    assert (queried.group_id, queried.leg_id) == ("group-1", "leg-1")
    assert (cancelled.group_id, cancelled.leg_id) == ("group-1", "leg-1")