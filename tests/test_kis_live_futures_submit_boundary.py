from dataclasses import dataclass
from decimal import Decimal
import pytest
from contracts.types import BrokerOrderCommand, BrokerOrderResponse
from environments.live.futures_broker_command_adapter import KisFuturesBrokerCommandAdapter
from environments.live.idempotency import IdempotencyRegistry, OrderIdentity
from environments.live.broker.kis_live_broker import LiveBrokerAdapter

class StubTransport:
    def __init__(self): self.auth_calls = 0; self.submitted = []
    def authenticate(self): self.auth_calls += 1; return True
    def submit(self, command):
        self.submitted.append(command)
        return BrokerOrderResponse(client_order_id=command.client_order_id, accepted=True, broker_order_id="KIS-ACK-1")

class StubGate:
    def __init__(self, allowed=True): self.allowed = allowed; self.calls = []
    def evaluate(self, quantity, account_age_seconds, **kwargs):
        self.calls.append((quantity, account_age_seconds)); return type("GateResult", (), {"allowed": self.allowed, "reason": "blocked"})()

class StubSymbolSource:
    def current_symbol(self): return "101W09"

@dataclass(frozen=True)
class LiveSafetyPolicyStub:
    can_submit: bool = True
    max_order_quantity: int = 10
    max_account_staleness_seconds: float = 30.0

def command():
    return BrokerOrderCommand(client_order_id="ORD-LIVE-1", instrument_id="FUT-1", side="BUY", quantity=2, order_type="LIMIT", broker_symbol=None, asset_type="FUTURES", requested_price=Decimal("350.10"), track_id="TRACK-1")

def identity(): return OrderIdentity("ORD-LIVE-1", "TRACK-1", "fp-1")

def live_adapter(transport, gate=None):
    return LiveBrokerAdapter(transport=transport, gate=gate or StubGate(), policy=LiveSafetyPolicyStub(), idempotency=IdempotencyRegistry(), futures_command_adapter=KisFuturesBrokerCommandAdapter(StubSymbolSource()))

def test_futures_submit_projects_authoritative_symbol_before_transport():
    transport = StubTransport(); broker = live_adapter(transport)
    assert broker.connect() is True
    result = broker.submit(command(), identity(), 1.0)
    assert result.accepted is True
    assert result.broker_order_id == "KIS-ACK-1"
    assert len(transport.submitted) == 1
    assert transport.submitted[0].broker_symbol == "101W09"
    assert transport.submitted[0].instrument_id == "FUT-1"
    assert isinstance(result, BrokerOrderResponse)

def test_safety_gate_blocks_before_transport():
    transport = StubTransport(); broker = live_adapter(transport, StubGate(allowed=False)); broker.connect()
    with pytest.raises(RuntimeError, match="blocked"):
        broker.submit(command(), identity(), 1.0)
    assert transport.submitted == []

def test_duplicate_identity_blocks_before_second_transport_submit():
    transport = StubTransport(); broker = live_adapter(transport); broker.connect()
    broker.submit(command(), identity(), 1.0)
    with pytest.raises(RuntimeError, match="duplicate client order identity"):
        broker.submit(command(), identity(), 1.0)
    assert len(transport.submitted) == 1

def test_missing_futures_adapter_fails_closed_before_transport():
    transport = StubTransport()
    broker = LiveBrokerAdapter(transport=transport, gate=StubGate(), policy=LiveSafetyPolicyStub(), idempotency=IdempotencyRegistry(), futures_command_adapter=None)
    broker.connect()
    with pytest.raises(RuntimeError, match="FUTURES_COMMAND_ADAPTER_REQUIRED"):
        broker.submit(command(), identity(), 1.0)
    assert transport.submitted == []
