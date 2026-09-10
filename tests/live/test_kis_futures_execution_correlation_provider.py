"""Test Kis Futures Execution Correlation Provider — test specification.

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
pass
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
"""
