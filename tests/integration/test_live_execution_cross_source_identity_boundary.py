from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from contracts.types import ExecutionReport
from environments.live.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.live.execution.kis_futures_execution_adapter import (
KISFuturesExecutionNoticeAdapter,
)


def _h0ifcni0_frame(*, order_id: str = "B1", quantity: str = "5", price: str = "101.6") -> str:
    values = [
        "CUST", "12345678", order_id, "", "01", "",
        "", "KOSPI200", quantity, price, "101530",
        "N", "Y", "Y", "001", "5", "", "KOSPI200",
        "", "", "1", price,
    ]
    return "0|H0IFCNI0|22|" + "^".join(values)


def _rest_report() -> ExecutionReport:
    return ExecutionReport(
        client_order_id="C1",
        broker_order_id="B1",
        execution_id="REST-CCNL-SNAPSHOT|B1|5|101.6",
        status="FILLED",
        filled_quantity=5,
        remaining_quantity=0,
        execution_price=Decimal("101.6"),
        execution_timestamp=None,
    )


def test_each_source_identity_is_replay_safe_but_not_cross_source_collapsed():
    rest_report = _rest_report()
    notice = KISFuturesExecutionNoticeAdapter().parse(_h0ifcni0_frame())
    h0_report = KISFuturesExecutionNoticeAdapter().to_execution_report(
notice,
        type("Context", (), {
            "client_order_id": "C1",
            "order_quantity": 5,
            "prior_filled_quantity": 0,
        })(),
    )

    assert rest_report.execution_id != h0_report.execution_id

    dedup = ExecutionEventDeduplicator()
    assert dedup.accept(rest_report) is True
    assert dedup.accept(rest_report) is False
    assert dedup.accept(h0_report) is True
    assert dedup.accept(h0_report) is False


def test_cross_source_identity_is_not_synthesized_from_shared_order_fields():
    rest_report = _rest_report()
    h0_report = replace(rest_report, execution_id="KIS-H0IFCNI0-wire-local")

    assert rest_report.broker_order_id == h0_report.broker_order_id
    assert rest_report.filled_quantity == h0_report.filled_quantity
    assert rest_report.execution_price == h0_report.execution_price
    assert rest_report.execution_id != h0_report.execution_id

    # Shared order/time/quantity/price fields do not authorize an identity merge.
    dedup = ExecutionEventDeduplicator()
    assert dedup.accept(rest_report) is True
    assert dedup.accept(h0_report) is True
