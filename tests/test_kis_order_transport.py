"""Test Kis Order Transport — test specification.

import json
import urllib.error
from contracts.types import BrokerOrderCommand
from environments.live.broker.kis_order_payload import (
KisDomesticFuturesOrderPayloadAdapter,
KisOrderAccountContext,
)
from environments.live.broker.kis_order_transport import (
KISDomesticFuturesOrderTransport,
KIS_FUTURES_ORDER_PATH,
KisOrderTransportError,
)
from infrastructure.kis.auth import KISAuthManager
class FakeResponse:
def __init__(self, body: bytes) -> None:
self.body = body
def __enter__(self):
return self
def __exit__(self, *_args):
return False
def read(self) -> bytes:
return self.body
def command(**changes):
values = {
"client_order_id": "CID-1",
"instrument_id": "FUT-1",
"side": "BUY",
"quantity": 2,
"order_type": "LIMIT",
"broker_symbol": "101W09AA",
"requested_price": 1.25,
"asset_type": "FUTURES",
}
values.update(changes)
return BrokerOrderCommand(**values)
def adapter(is_vts=False):
return KisDomesticFuturesOrderPayloadAdapter(
account=KisOrderAccountContext(cano="12345678", acnt_prdt_cd="01"),
is_vts=is_vts,
)
def test_real_post_uses_endpoint_headers_and_serialized_body():
calls = []
def fake_urlopen(request, timeout):
calls.append((request, timeout))
return FakeResponse(b'{"rt_cd":"0","msg_cd":"0","msg1":"OK","output":{"ODNO":"1234"}}')
auth = KISAuthManager()
transport = KISDomesticFuturesOrderTransport(
auth=auth,
payload_adapter=adapter(),
urlopen=fake_urlopen,
base_url="https://kis.test",
)
response = transport.submit(command())
assert response.accepted is True
assert response.broker_order_id == "1234"
request, timeout = calls[0]
assert timeout == 10.0
assert request.full_url == "https://kis.test" + KIS_FUTURES_ORDER_PATH
assert request.get_header("Tr_id") == "TTTO1101U"
assert request.get_header("Authorization") == "Bearer TOKEN"
assert json.loads(request.data.decode("utf-8"))["SHTN_PDNO"] == "101W09AA"
def test_vts_uses_vts_tr_id():
calls = []
def fake_urlopen(request, timeout):
calls.append(request)
return FakeResponse(b'{"rt_cd":"0","msg_cd":"0","msg1":"OK","output":{"ODNO":"5678"}}')
transport = KISDomesticFuturesOrderTransport(
auth=KISAuthManager(),
payload_adapter=adapter(is_vts=True),
urlopen=fake_urlopen,
)
response = transport.submit(command())
assert response.accepted is True
assert calls[0].get_header("Tr_id") == "VTTO1101U"
def test_failure_ack_is_normalized_and_is_not_execution():
response = KISDomesticFuturesOrderTransport.normalize_response(
"CID-2",
{"rt_cd": "1", "msg_cd": "ERR", "msg1": "rejected", "output": {}},
)
assert response.accepted is False
assert response.broker_order_id is None
assert response.broker_code == "ERR"
def test_missing_order_number_is_not_success_ack():
response = KISDomesticFuturesOrderTransport.normalize_response(
"CID-3",
{"rt_cd": "0", "msg_cd": "0", "msg1": "OK", "output": {}},
)
assert response.accepted is False
assert response.broker_order_id is None
def test_network_error_is_separate_from_broker_rejection():
def fake_urlopen(_request, timeout):
raise urllib.error.URLError("offline")
transport = KISDomesticFuturesOrderTransport(
auth=KISAuthManager(),
payload_adapter=adapter(),
urlopen=fake_urlopen,
)
try:
pass
transport.submit(command())
except KisOrderTransportError as exc:
pass
assert "transport failed" in str(exc)
else:
pass
raise AssertionError("network failure must not become a broker ACK")
"""
