from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from contracts.types import DataQuality, ExecutionReport
from environments.virtual.execution.virtual_execution import VirtualExecutionEngine


def test_authoritative_query_preserves_missing_fee_and_fill_provenance_from_submit_report():
    submitted = ExecutionReport(
        client_order_id="order-1",
        broker_order_id="broker-1",
        execution_id="exec-1",
        status="FILLED",
        filled_quantity=1,
        remaining_quantity=0,
        execution_price=Decimal("1.05"),
        execution_timestamp=datetime(2026, 10, 10, 9, 0, 0),
        fee=Decimal("12.5"),
        source_freshness=DataQuality(
            is_fresh=True, is_complete=True, source_available=True,
            reason="vssf_authoritative_execution",
        ),
    )
    queried = ExecutionReport(
        client_order_id="order-1",
        broker_order_id="broker-1",
        execution_id="exec-1",
        status="FILLED",
        filled_quantity=1,
        remaining_quantity=0,
        execution_price=None,
        execution_timestamp=None,
        fee=None,
        source_freshness=DataQuality(
            is_fresh=True, is_complete=True, source_available=True,
            reason="vssf_authoritative_order_lifecycle",
        ),
    )
    engine = VirtualExecutionEngine(
        position=None,
        account=None,
        authoritative_execute=lambda _order: submitted,
        authoritative_query=lambda _client_order_id: queried,
    )
    engine.execute(SimpleNamespace(client_order_id="order-1"))

    reconciled = engine.query("order-1")

    assert reconciled is not None
    assert reconciled.status == "FILLED"
    assert reconciled.execution_id == "exec-1"
    assert reconciled.filled_quantity == 1
    assert reconciled.execution_price == Decimal("1.05")
    assert reconciled.execution_timestamp == datetime(2026, 10, 10, 9, 0, 0)
    assert reconciled.fee == Decimal("12.5")
    assert reconciled.source_freshness.reason == "vssf_authoritative_order_lifecycle"
