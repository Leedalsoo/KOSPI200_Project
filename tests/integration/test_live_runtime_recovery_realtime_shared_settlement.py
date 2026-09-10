"""Test Live Runtime Recovery Realtime Shared Settlement — test specification.

from __future__ import annotations
import asyncio
from dataclasses import dataclass
from decimal import Decimal
from application.bootstrap import LiveRuntimeBootstrap
from application.composition.live_execution_runtime_composition_factory import (
create_live_execution_runtime_composition,
)
from contracts.types import BrokerOrderCommand, BrokerOrderResponse, OrderIntent
from core.oms.oms_fsm import OrderStateMachine
from environments.live.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.live.execution.kis_futures_execution_adapter import (
KISFuturesExecutionNoticeAdapter,
)
from environments.live.execution.kis_futures_execution_recovery_adapter import (
KISExecutionRecoveryContext,
KISFuturesExecutionRecoveryAdapter,
)
from environments.live.execution.kis_futures_execution_correlation_provider import (
KISFuturesExecutionCorrelationProvider,
)
from environments.live.position.live_execution_position_bridge import LivePositionFillAdapter
@dataclass
class FakePosition:
instrument_id: str
quantity: int = 0
average_price: Decimal | None = None
def apply_fill(self, *, side: str, quantity: int, price: Decimal) -> None:
self.quantity += quantity if side == "BUY" else -quantity
self.average_price = price
class FakeExecutionTransport:
def __init__(self, frames):
self.frames = list(frames)
self.connected = False
self.subscriptions = []
self.closed = False
async def connect(self):
self.connected = True
async def subscribe(self, tr_id, hts_id):
self.subscriptions.append((tr_id, hts_id))
async def recv(self):
return self.frames.pop(0)
async def close(self):
self.closed = True
class FakeRecoveryTransport:
def __init__(self, response):
self.response = response
self.queries = []
def inquire(self, query):
self.queries.append(query)
return self.response
class FakeBroker:
def submit(self, command, **_kwargs):
return BrokerOrderResponse(
client_order_id=command.client_order_id,
accepted=True,
broker_order_id="B1",
)
def _acked_oms() -> OrderStateMachine:
oms = OrderStateMachine()
oms.apply_intent(OrderIntent(
client_order_id="C1", instrument_id="I1", side="BUY", quantity=2, intent_type="OPEN"
))
oms.register_broker_order_command(BrokerOrderCommand(
client_order_id="C1", instrument_id="I1", side="BUY", quantity=2, order_type="MARKET"
))
oms.apply_ack(type("Ack", (), {
"client_order_id": "C1", "accepted": True, "broker_order_id": "B1"
})())
return oms
def _h0ifcni0_frame(*, broker_order_id="B1", qty="1", price="102.0") -> str:
values = [""] * 22
values[0] = "TESTCUST"
values[1] = "12345678-01"
values[2] = broker_order_id
values[4] = "02"
values[7] = "101T12"
values[8] = qty
values[9] = price
values[10] = "093015"
values[11] = "N"
values[12] = "Y"
values[13] = "Y"
values[14] = "00001"
values[15] = "2"
values[16] = "TEST"
values[17] = "KOSPI200 FUT"
values[19] = "G1"
values[20] = "1"
values[21] = price
return "0|H0IFCNI0|22|" + "^".join(values)
def _build_bootstrap():
oms = _acked_oms()
position = FakePosition("I1")
transport = FakeExecutionTransport([_h0ifcni0_frame()])
correlation = KISFuturesExecutionCorrelationProvider(oms)
composition = create_live_execution_runtime_composition(
transport=transport,
execution_adapter=KISFuturesExecutionNoticeAdapter(),
correlation_provider=correlation,
broker=FakeBroker(),
order_state_machine=oms,
position_fill_adapter=LivePositionFillAdapter(position),
execution_event_deduplicator=ExecutionEventDeduplicator(),
position_aggregate=position,
recovery_transport=FakeRecoveryTransport({
"output1": [{"odno": "B1", "tot_ccld_qty": "1", "avg_idx": "101"}]
}),
recovery_adapter=KISFuturesExecutionRecoveryAdapter(),
)
bootstrap = LiveRuntimeBootstrap(
execution=composition,
order_router=__import__("core.oms.order_router", fromlist=["StandardOrderRouter"]).StandardOrderRouter(
order_state_machine=oms,
broker_adapter=composition.broker,
),
)
return bootstrap, oms, position, transport
def test_bootstrap_uses_concrete_runtime_composition_for_start_receive_settle_close():
bootstrap, oms, position, transport = _build_bootstrap()
recovery_query = object()
recovered = bootstrap.startup_reconcile(recovery_query)
assert len(recovered) == 1
assert recovered[0].execution_id.startswith("REST-CCNL-SNAPSHOT|B1|1|")
assert recovered[0].execution_price == Decimal("101")
assert oms.get("C1").filled_quantity == 1
assert position.quantity == 1
asyncio.run(bootstrap.start_execution("HTS01"))
assert transport.connected is True
assert transport.subscriptions == [("H0IFCNI0", "HTS01")]
realtime = asyncio.run(bootstrap.receive_execution_once())
assert realtime.client_order_id == "C1"
assert realtime.broker_order_id == "B1"
assert realtime.filled_quantity == 1
assert realtime.execution_price == Decimal("102.0")
assert realtime.status == "FILLED"
assert oms.get("C1").filled_quantity == 2
assert oms.get("C1").remaining_quantity == 0
assert oms.get("C1").status == "FILLED"
assert position.quantity == 2
assert position.average_price == Decimal("102.0")
asyncio.run(bootstrap.close_execution())
assert transport.closed is True
def test_recovery_adapter_delta_price_remains_decimal_and_shared_contract_compatible():
adapter = KISFuturesExecutionRecoveryAdapter()
report = adapter.to_execution_report(
{"odno": "B1", "tot_ccld_qty": "2", "avg_idx": "101.5"},
KISExecutionRecoveryContext(
client_order_id="C1",
order_quantity=3,
prior_filled_quantity=1,
prior_average_price=Decimal("100.0"),
),
)
assert report is not None
assert report.filled_quantity == 1
assert report.execution_price == Decimal("103.0")
assert report.remaining_quantity == 1
"""
