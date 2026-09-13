from decimal import Decimal

import pytest

from contracts.types import ExecutionReport
from environments.live.execution.kis_futures_execution_adapter import KISFuturesExecutionAdapterInvalid, KISFuturesExecutionContext, KISFuturesExecutionNoticeAdapter


def frame(*, qty="2", price="351.25", cntg_yn="Y", order_qty="5"):
    values = [""] * 22
    values[0:4] = ["TESTCUST", "12345678-01", "00012345", ""]
    values[4:8] = ["02", "", "", "101T12"]
    values[8:12] = [qty, price, "093015", "N"]
    values[12:16] = [cntg_yn, "Y", "00001", order_qty]
    values[16:22] = ["TEST", "KOSPI200 FUT", "", "G1", "1", price]
    return "0|H0IFCNI0|22|" + "^".join(values)


def test_h0ifcni0_maps_partial_fill_to_execution_report():
    adapter = KISFuturesExecutionNoticeAdapter()
    notice = adapter.parse(frame(qty="2", order_qty="5"))
    report = adapter.to_execution_report(notice, KISFuturesExecutionContext("CLIENT-1", order_quantity=5, prior_filled_quantity=0))
    assert isinstance(report, ExecutionReport)
    assert report.client_order_id == "CLIENT-1"
    assert report.broker_order_id == "00012345"
    assert report.filled_quantity == 2
    assert report.remaining_quantity == 3
    assert report.status == "PARTIALLY_FILLED"
    assert report.execution_price == Decimal("351.25")


def test_h0ifcni0_maps_final_fill_to_filled():
    adapter = KISFuturesExecutionNoticeAdapter()
    notice = adapter.parse(frame(qty="2", order_qty="5"))
    report = adapter.to_execution_report(notice, KISFuturesExecutionContext("CLIENT-1", order_quantity=5, prior_filled_quantity=3))
    assert report.status == "FILLED"
    assert report.remaining_quantity == 0


def test_non_execution_notice_is_fail_closed():
    adapter = KISFuturesExecutionNoticeAdapter()
    notice = adapter.parse(frame(cntg_yn="N"))
    with pytest.raises(KISFuturesExecutionAdapterInvalid):
        adapter.to_execution_report(notice, KISFuturesExecutionContext("CLIENT-1", order_quantity=5))


def test_overfill_is_fail_closed():
    adapter = KISFuturesExecutionNoticeAdapter()
    notice = adapter.parse(frame(qty="3", order_qty="5"))
    with pytest.raises(KISFuturesExecutionAdapterInvalid):
        adapter.to_execution_report(notice, KISFuturesExecutionContext("CLIENT-1", order_quantity=5, prior_filled_quantity=3))


def test_wrong_tr_id_is_rejected():
    adapter = KISFuturesExecutionNoticeAdapter()
    with pytest.raises(KISFuturesExecutionAdapterInvalid):
        adapter.parse(frame().replace("H0IFCNI0", "H0IFCNT0"))
