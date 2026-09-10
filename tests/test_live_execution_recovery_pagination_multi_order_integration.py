"""Test Live Execution Recovery Pagination Multi Order Integration — test specification.

from __future__ import annotations
import json
from decimal import Decimal
from environments.live.execution.kis_futures_execution_recovery_adapter import (
KISExecutionRecoveryContext,
KISExecutionRecoveryQuery,
KISFuturesExecutionRecoveryAdapter,
)
from environments.live.execution.kis_futures_execution_recovery_service import (
LiveExecutionRecoveryService,
)
from environments.live.execution.kis_futures_execution_recovery_transport import (
KISFuturesExecutionRecoveryTransport,
)
class FakeResponse:
def __init__(self, body: dict, tr_cont: str):
self._body = json.dumps(body).encode("utf-8")
self.headers = {"tr_cont": tr_cont}
def __enter__(self):
return self
def __exit__(self, exc_type, exc, tb):
return False
def read(self):
return self._body
class FakeAuth:
base_url = "https://example.test"
def get_access_token(self):
return "TOKEN"
def get_auth_headers(self, tr_id: str = "", force_refresh: bool = False):
return {"tr_id": tr_id}
def test_recovery_consumes_multiple_pages_and_multiple_orders_through_service():
calls = []
def fake_urlopen(request, timeout):
calls.append(request)
if len(calls) == 1:
pass
return FakeResponse(
{
"rt_cd": "0",
"output1": [
{"odno": "A", "tot_ccld_qty": "2", "avg_idx": "100"},
{"odno": "B", "tot_ccld_qty": "1", "avg_idx": "200"},
],
"ctx_area_fk200": "FK2",
"ctx_area_nk200": "NK2",
},
"M",
)
return FakeResponse(
{
"rt_cd": "0",
"output1": [
{"odno": "A", "tot_ccld_qty": "5", "avg_idx": "102"},
{"odno": "B", "tot_ccld_qty": "4", "avg_idx": "201"},
],
},
"F",
)
transport = KISFuturesExecutionRecoveryTransport(
auth=FakeAuth(),
urlopen=fake_urlopen,
)
contexts = {
"A": KISExecutionRecoveryContext("CLIENT-A", 5),
"B": KISExecutionRecoveryContext("CLIENT-B", 4),
}
reports = []
service = LiveExecutionRecoveryService(
transport=transport,
adapter=KISFuturesExecutionRecoveryAdapter(),
correlation_provider=type(
"Provider",
(),
{"resolve": lambda self, order_id: contexts[order_id]},
)(),
on_report=reports.append,
)
result = service.recover(
KISExecutionRecoveryQuery("C", "03", "20260906", "20260906")
)
assert len(calls) == 2
assert calls[1].headers["tr_cont"] == "M"
assert "CTX_AREA_FK200=FK2" in calls[1].full_url
assert "CTX_AREA_NK200=NK2" in calls[1].full_url
assert len(result) == 4
assert [r.broker_order_id for r in reports] == ["A", "B", "A", "B"]
assert [r.filled_quantity for r in reports] == [2, 1, 3, 3]
assert reports[2].execution_price == Decimal("103.3333333333333333333333333")
assert reports[3].execution_price == Decimal("201.3333333333333333333333333")
assert all(r.execution_id.startswith("REST-CCNL-SNAPSHOT|") for r in reports)
"""
