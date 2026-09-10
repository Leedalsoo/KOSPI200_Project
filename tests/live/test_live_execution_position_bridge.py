"""Test Live Execution Position Bridge — test specification.

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
pass
bridge.settle(report)
assert aggregate.snapshot().qty == 0
def test_broker_client_correlation_conflict_fails_closed():
oms = OrderStateMachine()
oms.apply_intent(OrderIntent("C1", "I1", "BUY", 2, "NEW"))
oms.apply_intent(OrderIntent("C2", "I1", "BUY", 2, "NEW"))
oms.apply_ack(OrderAckEvent("C1", True, "B123"))
with pytest.raises(OrderStateTransitionError, match="BROKER_ORDER_ID_ALREADY_CORRELATED"):
pass
oms.apply_ack(OrderAckEvent("C2", True, "B123"))
with pytest.raises(Exception):
pass
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
"""
