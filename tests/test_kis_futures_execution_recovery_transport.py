"""Test Kis Futures Execution Recovery Transport — test specification.

from __future__ import annotations
import json
from types import SimpleNamespace
from environments.live.execution.kis_futures_execution_recovery_adapter import KISExecutionRecoveryQuery
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
def test_inquire_accumulates_official_continuation_pages():
calls = []
def fake_urlopen(request, timeout):
calls.append((request, timeout))
if len(calls) == 1:
pass
return FakeResponse(
{
"rt_cd": "0",
"output1": [{"odno": "B1", "tot_ccld_qty": "2"}],
"ctx_area_fk200": "FK2",
"ctx_area_nk200": "NK2",
},
"M",
)
return FakeResponse(
{
"rt_cd": "0",
"output1": [{"odno": "B2", "tot_ccld_qty": "5"}],
"ctx_area_fk200": "",
"ctx_area_nk200": "",
},
"F",
)
transport = KISFuturesExecutionRecoveryTransport(
auth=FakeAuth(),
urlopen=fake_urlopen,
)
result = transport.inquire(KISExecutionRecoveryQuery("C", "03", "20260906", "20260906"))
assert [row["odno"] for row in result["output1"]] == ["B1", "B2"]
assert len(calls) == 2
assert calls[1][0].headers["tr_cont"] == "M"
assert "CTX_AREA_FK200=FK2" in calls[1][0].full_url
assert "CTX_AREA_NK200=NK2" in calls[1][0].full_url
def test_inquire_stops_without_continuation():
calls = []
def fake_urlopen(request, timeout):
calls.append(request)
return FakeResponse(
{
"rt_cd": "0",
"output1": [{"odno": "B1", "tot_ccld_qty": "2"}],
},
"",
)
transport = KISFuturesExecutionRecoveryTransport(auth=FakeAuth(), urlopen=fake_urlopen)
result = transport.inquire(KISExecutionRecoveryQuery("C", "03", "20260906", "20260906"))
assert len(calls) == 1
assert result["output1"][0]["odno"] == "B1"
"""
