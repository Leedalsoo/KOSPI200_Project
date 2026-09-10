"""Test Live Execution Partial Fill Interleaving — test specification.

from __future__ import annotations
from decimal import Decimal
from contracts.types import ExecutionReport
from core.oms.oms_fsm import OrderStateMachine
from environments.live.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.live.position.live_execution_position_bridge import (
LiveExecutionPositionBridge,
LivePositionFillAdapter,
)
from environments.live.position.live_position_aggregate import LivePositionAggregate
def _build():
oms = OrderStateMachine()
oms.apply_intent(type("Intent", (), {"client_order_id": "C1", "instrument_id": "I1", "quantity": 5})())
command = type(
"Command",
(),
{
"client_order_id": "C1",
"instrument_id": "I1",
"side": "BUY",
"quantity": 5,
"order_type": "MARKET",
"broker_order_id": "B1",
},
)()
oms.register_broker_order_command(command)
oms.apply_ack(type("Ack", (), {"client_order_id": "C1", "accepted": True, "broker_order_id": "B1"})())
aggregate = LivePositionAggregate("I1")
dedup = ExecutionEventDeduplicator()
bridge = LiveExecutionPositionBridge(
order_state_machine=oms,
position_fill_adapter=LivePositionFillAdapter(aggregate),
execution_event_deduplicator=dedup,
position_aggregate=aggregate,
)
return oms, aggregate, dedup, bridge
def test_recovery_realtime_recovery_partial_fill_interleaving_preserves_cumulative_quantity_and_average():
oms, aggregate, dedup, bridge = _build()
bridge.settle(ExecutionReport("C1", "B1", "REST|B1|2|101", "PARTIALLY_FILLED", 2, 3, Decimal("101"), None))
bridge.settle(ExecutionReport("C1", "B1", "H0IFCNI0|E1", "PARTIALLY_FILLED", 1, 2, Decimal("102"), None))
bridge.settle(ExecutionReport("C1", "B1", "REST|B1|5|101.6", "FILLED", 2, 0, Decimal("102"), None))
state = oms.get("C1")
snapshot = aggregate.snapshot()
assert state is not None and state.status == "FILLED" and state.filled_quantity == 5
assert state.average_execution_price == Decimal("101.6")
assert snapshot.qty == 5
assert snapshot.avg_price == 101.6
def test_stale_recovery_snapshot_after_newer_realtime_fill_fails_closed_without_mutation():
oms, aggregate, dedup, bridge = _build()
bridge.settle(ExecutionReport("C1", "B1", "H0IFCNI0|E1", "PARTIALLY_FILLED", 3, 2, Decimal("101"), None))
before = (oms.get("C1").filled_quantity, aggregate.snapshot().qty, aggregate.snapshot().avg_price)
stale = ExecutionReport("C1", "B1", "REST|B1|2|100.5", "PARTIALLY_FILLED", 2, 3, Decimal("100.5"), None)
try:
pass
bridge.settle(stale)
except ValueError as exc:
pass
assert str(exc) == "REMAINING_QUANTITY_MISMATCH"
else:
pass
raise AssertionError("stale cumulative snapshot must not be applied as a fresh delta")
after = (oms.get("C1").filled_quantity, aggregate.snapshot().qty, aggregate.snapshot().avg_price)
assert after == before
assert not dedup.contains(stale.execution_id)
"""
