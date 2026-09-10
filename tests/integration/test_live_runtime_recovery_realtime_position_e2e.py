"""Test Live Runtime Recovery Realtime Position E2E — test specification.

from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from contracts.types import BrokerOrderCommand, ExecutionReport, OrderIntent
from core.oms.oms_fsm import OrderStateMachine
from environments.live.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.live.execution.live_execution_recovery_service import LiveExecutionRecoveryService
from environments.live.position.live_execution_position_bridge import LiveExecutionPositionBridge, LivePositionFillAdapter
@dataclass
class FakePosition:
instrument_id: str
quantity: int = 0
average_price: float | None = None
def apply_fill(self, *, side: str, quantity: int, price: float) -> None:
self.quantity += quantity if side == "BUY" else -quantity
self.average_price = price
@dataclass(frozen=True)
class Correlation:
client_order_id: str
order_quantity: int
prior_filled_quantity: int
prior_average_price: float | None = None
class FakeCorrelationProvider:
def __init__(self, correlation: Correlation):
self.correlation = correlation
def resolve(self, broker_order_id: str):
return self.correlation
class FakeRecoveryTransport:
def __init__(self, response):
self.response = response
self.queries = []
def inquire(self, query):
self.queries.append(query)
return self.response
class FakeRecoveryAdapter:
def normalize(self, response, context_for_order):
row = response["output1"][0]
context = context_for_order(row["odno"])
return [ExecutionReport(
client_order_id=context.client_order_id,
broker_order_id=row["odno"],
execution_id=row["exec_id"],
status="PARTIALLY_FILLED",
filled_quantity=row["delta_qty"],
remaining_quantity=context.order_quantity - context.prior_filled_quantity - row["delta_qty"],
execution_price=Decimal(str(row["price"])),
execution_timestamp=None,
)]
def _acked_oms() -> OrderStateMachine:
oms = OrderStateMachine()
oms.apply_intent(OrderIntent(client_order_id="C1", instrument_id="I1", side="BUY", quantity=2, intent_type="OPEN"))
oms.register_broker_order_command(BrokerOrderCommand(
client_order_id="C1", instrument_id="I1", side="BUY", quantity=2, order_type="MARKET"
))
oms.apply_ack(type("Ack", (), {"client_order_id": "C1", "accepted": True, "broker_order_id": "B1"})())
return oms
def test_startup_recovery_then_realtime_execution_preserves_oms_position_and_replay_invariants():
oms = _acked_oms()
position = FakePosition("I1")
bridge = LiveExecutionPositionBridge(
order_state_machine=oms,
position_fill_adapter=LivePositionFillAdapter(position),
execution_event_deduplicator=ExecutionEventDeduplicator(),
position_aggregate=position,
)
recovery = LiveExecutionRecoveryService(
transport=FakeRecoveryTransport({"output1": [{"odno": "B1", "exec_id": "REST-E1", "delta_qty": 1, "price": 101.0}]}),
adapter=FakeRecoveryAdapter(),
correlation_provider=FakeCorrelationProvider(Correlation("C1", 2, 0)),
on_report=bridge.settle,
)
recovered = recovery.recover(object())
assert len(recovered) == 1
assert oms.get("C1").filled_quantity == 1
assert position.quantity == 1
realtime = ExecutionReport(
client_order_id="C1", broker_order_id="B1", execution_id="H0IFCNI0-E2",
status="FILLED", filled_quantity=1, remaining_quantity=0,
execution_price=Decimal("102.0"), execution_timestamp=None,
)
bridge.settle(realtime)
bridge.settle(realtime)
assert oms.get("C1").filled_quantity == 2
assert oms.get("C1").remaining_quantity == 0
assert oms.get("C1").status == "FILLED"
assert position.quantity == 2
assert position.average_price == 102.0
def test_terminal_order_replay_is_deduplicated_before_state_guard():
oms = _acked_oms()
position = FakePosition("I1")
bridge = LiveExecutionPositionBridge(
order_state_machine=oms,
position_fill_adapter=LivePositionFillAdapter(position),
execution_event_deduplicator=ExecutionEventDeduplicator(),
position_aggregate=position,
)
report = ExecutionReport(
client_order_id="C1", broker_order_id="B1", execution_id="E1",
status="FILLED", filled_quantity=2, remaining_quantity=0,
execution_price=Decimal("101.0"), execution_timestamp=None,
)
bridge.settle(report)
bridge.settle(report)
assert oms.get("C1").filled_quantity == 2
assert position.quantity == 2
"""
