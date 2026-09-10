"""Test Kis Futures Execution Consumer — test specification.

import asyncio
import base64
import json
import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from environments.live.execution.kis_futures_execution_adapter import KISFuturesExecutionNoticeAdapter
from environments.live.execution.kis_futures_execution_consumer import KISFuturesExecutionConsumer
from environments.live.execution.kis_futures_execution_correlation_provider import KISFuturesExecutionCorrelationProvider
from infrastructure.kis.futures_execution_transport import FuturesExecutionTransportError, KISFuturesExecutionTransport
class FakeAuth:
is_vts = False
app_key = "APP"
app_secret = "SECRET"
base_url = "https://invalid.example"
def has_credentials(self): return True
class FakeSocket:
def __init__(self, messages): self.messages = list(messages); self.sent = []
async def send(self, message): self.sent.append(message)
async def recv(self): return self.messages.pop(0)
async def close(self): return None
def _encrypt(plain: str, key: str, iv: str) -> str:
padder = padding.PKCS7(algorithms.AES.block_size).padder()
padded = padder.update(plain.encode()) + padder.finalize()
encryptor = Cipher(algorithms.AES(key.encode()), modes.CBC(iv.encode())).encryptor()
encrypted = encryptor.update(padded) + encryptor.finalize()
return base64.b64encode(encrypted).decode()
def _plain_h0ifcni0_frame() -> str:
values = ["C", "A", "B123", "O", "02", "00", "00", "K200", "2", "350.0", "101010", "N", "Y", "Y", "01", "5", "N", "KOSPI", "00", "1", "1", "350.0"]
return "^".join(values)
def test_execution_transport_decrypts_h0ifcni0_and_preserves_envelope():
key = "0123456789abcdef0123456789abcdef"
iv = "abcdef0123456789"
socket = FakeSocket([
json.dumps({"header": {"tr_id": "H0IFCNI0"}, "body": {"rt_cd": "0", "output": {"key": key, "iv": iv}}}),
"1|H0IFCNI0|1|" + _encrypt(_plain_h0ifcni0_frame(), key, iv),
])
async def socket_factory(_): return socket
transport = KISFuturesExecutionTransport(FakeAuth(), socket_factory=socket_factory)
transport._issue_approval_key = lambda: "approval-for-test"
async def run():
await transport.connect(); await transport.subscribe("H0IFCNI0", "HTS01"); return await transport.recv()
frame = asyncio.run(run())
assert frame == "1|H0IFCNI0|22|" + _plain_h0ifcni0_frame()
assert json.loads(socket.sent[0])["body"]["input"] == {"tr_id": "H0IFCNI0", "tr_key": "HTS01"}
def test_execution_consumer_resolves_oms_context_and_emits_execution_report():
key = "0123456789abcdef0123456789abcdef"
iv = "abcdef0123456789"
socket = FakeSocket([
json.dumps({"header": {"tr_id": "H0IFCNI0"}, "body": {"rt_cd": "0", "output": {"key": key, "iv": iv}}}),
"1|H0IFCNI0|1|" + _encrypt(_plain_h0ifcni0_frame(), key, iv),
])
async def socket_factory(_): return socket
transport = KISFuturesExecutionTransport(FakeAuth(), socket_factory=socket_factory)
transport._issue_approval_key = lambda: "approval-for-test"
correlation = type("Correlation", (), {"client_order_id": "C1", "order_quantity": 5, "prior_filled_quantity": 0})()
provider = KISFuturesExecutionCorrelationProvider({"B123": correlation})
reports = []
async def run():
consumer = KISFuturesExecutionConsumer(transport, KISFuturesExecutionNoticeAdapter(), provider, reports.append)
await consumer.start("HTS01"); return await consumer.receive_once()
report = asyncio.run(run())
assert report.client_order_id == "C1"
assert report.broker_order_id == "B123"
assert report.filled_quantity == 2
assert report.remaining_quantity == 3
assert len(reports) == 1
"""
