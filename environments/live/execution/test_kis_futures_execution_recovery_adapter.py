"""Test Kis Futures Execution Recovery Adapter — 테스트 사양 문서.

from decimal import Decimal
import pytest
from environments.live.execution.kis_futures_execution_recovery_adapter import (
KISExecutionRecoveryInvalid,
KISExecutionRecoveryContext,
KISExecutionRecoveryQuery,
KISFuturesExecutionRecoveryAdapter,
)
def row(**overrides):
value = {
"odno": "00012345",
"ord_qty": "5",
"tot_ccld_qty": "2",
"avg_idx": "350.25",
"ord_dt": "20260906",
"ord_tmd": "101530",
}
value.update(overrides)
return value
def context(**overrides):
value = {
"client_order_id": "CLIENT-1",
"order_quantity": 5,
"prior_filled_quantity": 0,
"prior_average_price": None,
}
value.update(overrides)
return KISExecutionRecoveryContext(**value)
def test_real_request_contract_matches_official_inquire_ccnl():
path, tr_id, params = KISFuturesExecutionRecoveryAdapter().build_request(
KISExecutionRecoveryQuery("12345678", "03", "20260906", "20260906")
)
assert path == "/uapi/domestic-futureoption/v1/trading/inquire-ccnl"
assert tr_id == "TTTO5201R"
assert params["CCLD_NCCS_DVSN"] == "01"
assert params["SLL_BUY_DVSN_CD"] == "00"
assert params["SORT_SQN"] == "DS"
assert params["CTX_AREA_FK200"] == ""
assert params["CTX_AREA_NK200"] == ""
def test_vts_request_uses_vt_tr_id():
query = KISExecutionRecoveryQuery("12345678", "03", "20260906", "20260906", virtual=True)
assert query.tr_id == "VTTO5201R"
def test_official_order_snapshot_maps_cumulative_total_to_delta_report():
report = KISFuturesExecutionRecoveryAdapter().to_execution_report(row(), context())
assert report is not None
assert report.execution_id == "REST-CCNL-SNAPSHOT|00012345|2|350.25"
assert report.filled_quantity == 2
assert report.execution_price == Decimal("350.25")
assert report.status == "PARTIALLY_FILLED"
assert report.remaining_quantity == 3
def test_recovery_snapshot_uses_prior_fill_and_average_to_calculate_delta_price():
report = KISFuturesExecutionRecoveryAdapter().to_execution_report(
row(tot_ccld_qty="5", avg_idx="351.00"),
context(prior_filled_quantity=2, prior_average_price=Decimal("350.25")),
)
assert report is not None
assert report.filled_quantity == 3
assert report.execution_price == Decimal("351.50")
assert report.remaining_quantity == 0
assert report.status == "FILLED"
def test_preexisting_partial_recovery_without_prior_average_fails_closed():
with pytest.raises(KISExecutionRecoveryInvalid, match="PRIOR_AVERAGE_PRICE_REQUIRED_FOR_DELTA_PRICE"):
pass
KISFuturesExecutionRecoveryAdapter().to_execution_report(
row(tot_ccld_qty="5", avg_idx="351.00"),
context(prior_filled_quantity=2),
)
def test_order_date_and_time_reconstruct_execution_timestamp():
report = KISFuturesExecutionRecoveryAdapter().to_execution_report(row(), context())
assert report is not None
assert report.execution_timestamp is not None
assert report.execution_timestamp.strftime("%Y%m%d%H%M%S") == "20260906101530"
def test_repeated_same_snapshot_produces_no_new_execution():
report = KISFuturesExecutionRecoveryAdapter().to_execution_report(
row(tot_ccld_qty="2"),
context(prior_filled_quantity=2),
)
assert report is None
def test_cumulative_regression_fails_closed():
with pytest.raises(KISExecutionRecoveryInvalid, match="CUMULATIVE_FILLED_QUANTITY_REGRESSION"):
pass
KISFuturesExecutionRecoveryAdapter().to_execution_report(
row(tot_ccld_qty="1"), context(prior_filled_quantity=2)
)
def test_response_output1_normalization_uses_order_context():
adapter = KISFuturesExecutionRecoveryAdapter()
reports = adapter.normalize(
{
"output1": [
row(odno="B1", tot_ccld_qty="2"),
row(odno="B2", tot_ccld_qty="5", avg_idx="351.25"),
]
},
lambda order_id: context(client_order_id=f"C-{order_id}"),
)
assert [report.client_order_id for report in reports] == ["C-B1", "C-B2"]
assert [report.filled_quantity for report in reports] == [2, 5]
"""
