[Child Page] live_environment_test_spec.md
## Structural
    - Live credential names are separate from Paper/VTS credentials.
    - Live has no VSSF/VMS synthetic fallback.
    - Live starts DISARMED.
    - Live order submission requires explicit approval, limits, non-stale account/position state and an active broker connection.
## Safety
    - Kill Switch blocks every new order.
    - Order quantity, daily loss and position limits are mandatory.
    - Duplicate client order identity cannot create a second submission.
    - Timeout/retry must query broker state before any resend.
## Recovery
    - Startup reads Broker Account/Position before resume.
    - Broker/internal mismatch causes SAFE_STOP.
    - Restart must not resend an already accepted order.
## External evidence
    - Mock responses are never PASS for Live operation.
    - Real credential, real Account/Position response and approved minimal-order evidence are required for EXTERNAL SYSTEM PROVEN.
    - Physical execution is currently expected to remain BLOCKED without credentials/network/human approval.

[Child Page] test_live_execution_position_bridge.py
```python
from decimal import Decimal

import pytest

from contracts.types import BrokerOrderCommand, OrderAckEvent, OrderIntent
from core.oms.oms_fsm import OrderStateMachine, OrderStateTransitionError
from environments.live.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.live.execution.kis_futures_execution_adapter import (
    KISFuturesExecutionContext,
    KISFuturesExecutionNoticeAdapter,
)
from environments.live.execution.kis_futures_execution_correlation_provider import (
    KISFuturesExecutionCorrelationProvider,
)
from environments.live.position.live_execution_position_bridge import LiveExecutionPositionBridge
from environments.live.position.live_position_fill_adapter import LivePositionFillAdapter
from environments.live.position.live_position_aggregate import LivePositionAggregate


def _frame(order_no="B123", qty="2", price="350.0"):
    values = [
        "C", "A", order_no, "O", "02", "00", "00", "K200", qty, price,
        "101010", "N", "Y", "Y", "01", "2", "N", "KOSPI", "00", "1", "1", price,
    ]
    return "0|H0IFCNI0|22|" + "^".join(values)


def test_h0ifcni0_full_seam_duplicate_execution_applies_position_once():
    oms = OrderStateMachine()
    oms.apply_intent(OrderIntent("C1", "I1", "BUY", 5, "NEW"))
    oms.apply_ack(OrderAckEvent("C1", True, "B123"))
    command = BrokerOrderCommand("C1", "I1", "BUY", 5, "MARKET")
    oms.register_broker_order_command(command)

    adapter = KISFuturesExecutionNoticeAdapter()
    notice = adapter.parse(_frame())
    correlation = KISFuturesExecutionCorrelationProvider(oms).resolve(notice.broker_order_id)
    report = adapter.to_execution_report(
        notice,
        KISFuturesExecutionContext(
            correlation.client_order_id,
            correlation.order_quantity,
            correlation.prior_filled_quantity,
        ),
    )

    aggregate = LivePositionAggregate("I1")
    bridge = LiveExecutionPositionBridge(
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(aggregate),
        execution_event_deduplicator=ExecutionEventDeduplicator(),
        position_aggregate=aggregate,
    )

    first = bridge.settle(report)
    second = bridge.settle(report)

    assert first.filled_quantity == 2
    assert second.filled_quantity == 2
    snapshot = aggregate.snapshot()
    assert snapshot.qty == 2
    assert snapshot.avg_price == Decimal("350.0")


def test_execution_before_ack_fails_closed_and_position_is_unchanged():
    oms = OrderStateMachine()
    oms.apply_intent(OrderIntent("C1", "I1", "BUY", 2, "NEW"))
    command = BrokerOrderCommand("C1", "I1", "BUY", 2, "MARKET")
    oms.register_broker_order_command(command)

    notice = KISFuturesExecutionNoticeAdapter().parse(_frame(qty="2"))
    report = KISFuturesExecutionNoticeAdapter().to_execution_report(
        notice,
        KISFuturesExecutionContext("C1", 2, 0),
    )
    aggregate = LivePositionAggregate("I1")
    bridge = LiveExecutionPositionBridge(
        order_state_machine=oms,
        position_fill_adapter=LivePositionFillAdapter(aggregate),
        execution_event_deduplicator=ExecutionEventDeduplicator(),
        position_aggregate=aggregate,
    )

    with pytest.raises(OrderStateTransitionError, match="EXECUTION_BEFORE_ACK"):
        bridge.settle(report)

    assert aggregate.snapshot().qty == 0


def test_broker_client_correlation_conflict_fails_closed():
    oms = OrderStateMachine()
    oms.apply_intent(OrderIntent("C1", "I1", "BUY", 2, "NEW"))
    oms.apply_intent(OrderIntent("C2", "I1", "BUY", 2, "NEW"))
    oms.apply_ack(OrderAckEvent("C1", True, "B123"))

    with pytest.raises(OrderStateTransitionError, match="BROKER_ORDER_ID_ALREADY_CORRELATED"):
        oms.apply_ack(OrderAckEvent("C2", True, "B123"))

    with pytest.raises(Exception):
        KISFuturesExecutionCorrelationProvider(oms).resolve("UNKNOWN")


def test_partial_fill_updates_oms_correlation_prior_quantity():
    oms = OrderStateMachine()
    oms.apply_intent(OrderIntent("C1", "I1", "BUY", 5, "NEW"))
    oms.apply_ack(OrderAckEvent("C1", True, "B123"))
    adapter = KISFuturesExecutionNoticeAdapter()
    notice = adapter.parse(_frame(qty="2"))
    provider = KISFuturesExecutionCorrelationProvider(oms)
    correlation = provider.resolve("B123")
    report = adapter.to_execution_report(
        notice,
        KISFuturesExecutionContext(
            correlation.client_order_id,
            correlation.order_quantity,
            correlation.prior_filled_quantity,
        ),
    )
    oms.apply_execution(report)

    assert provider.resolve("B123").prior_filled_quantity == 2
```
## 검증 범위
    - H0IFCNI0 → OMS correlation → ExecutionReport → dedup → OMS FSM → Position의 targeted seam을 검증한다.
    - LiveExecutionPositionBridge.settle(report)의 현재 계약에 맞춰 기존 stale test 호출을 정정했다.
    - BrokerOrderCommand는 OMS-owned correlation에 먼저 등록한다.
    - Decimal 기반 Position 평균가격 invariant를 명시적으로 검증한다.
    - 실제 KIS network, credential, account, order submission은 사용하지 않는다.

[Child Page] test_kis_futures_execution_correlation_provider.py
```python
from datetime import datetime
from decimal import Decimal

import pytest

from contracts.types import ExecutionReport, OrderAckEvent, OrderIntent
from core.oms.oms_fsm import OrderStateMachine, OrderStateTransitionError
from environments.live.execution.kis_futures_execution_adapter import (
    KISFuturesExecutionContext,
    KISFuturesExecutionNoticeAdapter,
)
from environments.live.execution.kis_futures_execution_correlation_provider import (
    KISFuturesExecutionCorrelationError,
    KISFuturesExecutionCorrelationProvider,
)


_FIELDS = [
    "cust", "account", "BRK-1001", "", "01", "00", "1", "101W09",
    "2", "101.50", "123456", "N", "Y", "Y", "001", "5", "name",
    "KOSPI200", "00", "1", "1", "101.50",
]


def _frame() -> str:
    return "0|H0IFCNI0|22|" + "^".join(_FIELDS)


def test_ack_creates_oms_authoritative_execution_correlation():
    fsm = OrderStateMachine()
    fsm.apply_intent(OrderIntent(
        client_order_id="CLIENT-1",
        instrument_id="FUT-1",
        side="BUY",
        quantity=5,
        intent_type="OPEN",
    ))
    fsm.apply_ack(OrderAckEvent(
        client_order_id="CLIENT-1",
        accepted=True,
        broker_order_id="BRK-1001",
    ))

    correlation = KISFuturesExecutionCorrelationProvider(fsm).resolve("BRK-1001")
    assert correlation.client_order_id == "CLIENT-1"
    assert correlation.broker_order_id == "BRK-1001"
    assert correlation.order_quantity == 5
    assert correlation.prior_filled_quantity == 0
    assert correlation.prior_average_price is None


def test_h0ifcni0_notice_uses_oms_correlation_without_synthetic_identity():
    fsm = OrderStateMachine()
    fsm.apply_intent(OrderIntent(
        client_order_id="CLIENT-2",
        instrument_id="FUT-2",
        side="BUY",
        quantity=5,
        intent_type="OPEN",
    ))
    fsm.apply_ack(OrderAckEvent(
        client_order_id="CLIENT-2",
        accepted=True,
        broker_order_id="BRK-1001",
    ))

    provider = KISFuturesExecutionCorrelationProvider(fsm)
    correlation = provider.resolve("BRK-1001")
    notice = KISFuturesExecutionNoticeAdapter().parse(_frame())
    context = KISFuturesExecutionContext(
        client_order_id=correlation.client_order_id,
        order_quantity=correlation.order_quantity,
        prior_filled_quantity=correlation.prior_filled_quantity,
    )
    report = KISFuturesExecutionNoticeAdapter().to_execution_report(notice, context)

    assert report.client_order_id == "CLIENT-2"
    assert report.broker_order_id == "BRK-1001"
    assert report.filled_quantity == 2
    assert report.remaining_quantity == 3


def test_unknown_broker_order_id_fails_closed():
    fsm = OrderStateMachine()
    provider = KISFuturesExecutionCorrelationProvider(fsm)
    with pytest.raises(KISFuturesExecutionCorrelationError):
        provider.resolve("UNKNOWN")


def test_second_fill_uses_updated_prior_filled_quantity():
    fsm = OrderStateMachine()
    fsm.apply_intent(OrderIntent(
        client_order_id="CLIENT-3",
        instrument_id="FUT-3",
        side="BUY",
        quantity=5,
        intent_type="OPEN",
    ))
    fsm.apply_ack(OrderAckEvent(
        client_order_id="CLIENT-3",
        accepted=True,
        broker_order_id="BRK-1001",
    ))
    provider = KISFuturesExecutionCorrelationProvider(fsm)
    adapter = KISFuturesExecutionNoticeAdapter()
    first = adapter.to_execution_report(
        adapter.parse(_frame()),
        KISFuturesExecutionContext("CLIENT-3", 5, 0),
    )
    fsm.apply_execution(first)

    correlation = provider.resolve("BRK-1001")
    assert correlation.prior_filled_quantity == 2
    assert correlation.prior_average_price == Decimal("101.50")
```
## 검증 의도
    - accepted ACK만 broker_order_id → client_order_id 상관관계를 만든다.
    - H0IFCNI0 notice는 broker order number를 사용해 OMS 상태를 조회하고, client_order_id/order_quantity/prior_filled_quantity를 synthetic 생성하지 않는다.
    - unknown broker order는 ExecutionReport 생성 전에 fail-closed한다.
    - 부분체결 후 다음 notice는 OMS가 보존한 누적 체결수량을 사용한다.
    - 실제 KIS network/실계좌/실주문은 사용하지 않는다.

[Child Page] test_kis_futures_execution_consumer.py
```python
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
```
def test_execution_transport_reconnect_close_start_and_subscription_ownership():
sockets = [FakeSocket([]), FakeSocket([])]
async def socket_factory(_):
return sockets.pop(0)
transport = KISFuturesExecutionTransport(FakeAuth(), socket_factory=socket_factory)
transport._issue_approval_key = lambda: "approval-for-test"
async def run():
await transport.connect()
with pytest.raises(FuturesExecutionTransportError, match="already connected"):
await transport.connect()
await transport.subscribe("H0IFCNI0", "HTS01")
with pytest.raises(FuturesExecutionTransportError, match="subscription is already active"):
await transport.subscribe("H0IFCNI0", "HTS01")
await transport.close()
await transport.connect()
await transport.subscribe("H0IFCNI0", "HTS01")
await transport.close()
asyncio.run(run())
assert len(sockets) == 0
검증 범위: encrypted KIS frame → dedicated execution transport → H0IFCNI0 adapter → OMS correlation → ExecutionReport 및 reconnect/close/start 반복 시 connection·subscription ownership. 실제 KIS 네트워크/credential/account/order는 사용하지 않는다.

[Child Page] test_live_position_aggregate_risk_source.py
```python
import pytest
from environments.live.position.live_position_aggregate import LivePositionAggregate
from environments.live.position.live_position_aggregate_risk_source import LivePositionAggregateRiskSource
from core.position.position_aggregate_risk_adapter import position_aggregate_to_risk_input

def test_live_aggregate_projects_authoritative_state_to_risk_input():
    a = LivePositionAggregate("OPT-1")
    a.apply_fill(side="BUY", quantity=3, price=1.25)
    risk = position_aggregate_to_risk_input(LivePositionAggregateRiskSource({"OPT-1": a}))
    assert risk.positions["OPT-1"].side == "BUY"
    assert risk.positions["OPT-1"].qty == 3

def test_flat_position_is_excluded():
    assert LivePositionAggregateRiskSource({"OPT-1": LivePositionAggregate("OPT-1")}).snapshot() == {}

def test_identity_mismatch_fails_closed():
    with pytest.raises(ValueError, match="LIVE_POSITION_INSTRUMENT_ID_MISMATCH"):
        LivePositionAggregateRiskSource({"OTHER": LivePositionAggregate("OPT-1")}).snapshot()
```
Covers authoritative projection, flat exclusion, and identity mismatch fail-closed.

[Child Page] test_live_runtime_risk_state_factory.py
```python
import pytest
from application.composition.live_runtime_risk_state_factory import create_live_runtime_risk_state_providers

class Account:
    def snapshot(self): return "authoritative-account"
class Position:
    def snapshot(self): return {}

def test_authoritative_account_and_position_are_exposed_without_synthesis():
    p=create_live_runtime_risk_state_providers(account=Account(), position_source=Position())
    assert p.account_snapshot_provider()=="authoritative-account"
    assert p.position_source_provider().snapshot()=={}

def test_missing_account_fails_closed():
    with pytest.raises(ValueError, match="LIVE_ACCOUNT_PROVIDER_REQUIRED"):
        create_live_runtime_risk_state_providers(account=None, position_source=Position())
```
Authoritative provider exposure and missing-account fail-closed coverage.

[Child Page] test_live_runtime_tick_authoritative_wiring.py
```python
import pytest

from application.composition.live_runtime_tick_entry import LiveRuntimeTickEntry


class Runtime:
    def process_tick(self, tick, observed_at):
        return ("evaluation",)

class S2D:
    def evaluate(self, evaluations):
        return ("decision",)

class D2C:
    def commands(self, decisions, evaluations):
        return ("command",)

class Context:
    def __init__(self):
        self.account_snapshot = "stale"
        self.position_source = "stale"
        self.order_router = object()
        self.broker_command = object()

def test_tick_entry_refreshes_authoritative_state_and_uses_actual_route_contract():
    seen = []
    def route(command, *, risk_gate, context):
        seen.append((command, risk_gate, context.account_snapshot, context.position_source))
        return "ALLOW"

    entry = LiveRuntimeTickEntry(
        Runtime(), S2D(), D2C(), "gate", route,
        lambda: "live-account", lambda: "live-position"
    )
    result = entry.process_tick("tick", "time", risk_context=Context())
    assert result == ("ALLOW",)
    assert seen == [("command", "gate", "live-account", "live-position")]

def test_missing_authoritative_state_fails_closed():
    entry = LiveRuntimeTickEntry(
        Runtime(), S2D(), D2C(), "gate", lambda **_: None,
        lambda: None, lambda: "position"
    )
    with pytest.raises(ValueError, match="RUNTIME_RISK_AUTHORITATIVE_STATE_REQUIRED"):
        entry.process_tick("tick", "time", risk_context=Context())
```
Actual route contract, per-call authoritative state refresh, and fail-closed coverage.