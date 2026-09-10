"""Test Futures Market Transport — 테스트 사양 문서.

import asyncio
import json
from infrastructure.kis.futures_market_transport import (
FuturesMarketTransportError,
KISFuturesMarketTransport,
KISFuturesMarketTransportConfig,
)
class _FakeApproval:
def issue(self):
return "approval-test"
class _FakeSocket:
def __init__(self):
self.sent = []
self.closed = False
self.received = "0|H0IFCNT0|37|101S12^093000^^^^^^^^^^123^^^"
async def send(self, value):
self.sent.append(value)
async def recv(self):
return self.received
async def close(self):
self.closed = True
def _transport():
transport = object.__new__(KISFuturesMarketTransport)
transport._config = KISFuturesMarketTransportConfig(is_vts=False)
transport._approval = _FakeApproval()
transport._socket = _FakeSocket()
transport._connected = True
return transport
def test_subscription_message_preserves_tr_id_and_symbol():
transport = _transport()
asyncio.run(transport.subscribe("H0IFCNT0", "101S12"))
message = json.loads(transport._socket.sent[0])
assert message["header"]["approval_key"] == "approval-test"
assert message["header"]["tr_type"] == "1"
assert message["body"]["input"] == {"tr_id": "H0IFCNT0", "tr_key": "101S12"}
def test_unconnected_transport_fails_closed():
transport = _transport()
transport._connected = False
try:
pass
asyncio.run(transport.subscribe("H0IFCNT0", "101S12"))
except FuturesMarketTransportError as exc:
pass
assert "not connected" in str(exc)
else:
pass
raise AssertionError("expected FuturesMarketTransportError")
"""
