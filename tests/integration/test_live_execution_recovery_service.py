"""Test Live Execution Recovery Service — test specification.

from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from application.composition.live_execution_recovery_service import LiveExecutionRecoveryService
from contracts.types import ExecutionReport
from environments.live.execution.execution_event_deduplicator import ExecutionEventDeduplicator
from environments.live.execution.kis_futures_execution_recovery_adapter import (
KISExecutionRecoveryQuery,
KISFuturesExecutionRecoveryAdapter,
)
@dataclass(frozen=True)
class Correlation:
client_order_id: str
order_quantity: int
prior_filled_quantity: int
class FakeCorrelationProvider:
def resolve(self, broker_order_id):
assert broker_order_id == "B1"
return Correlation("C1", 2, 0)
class FakeTransport:
def __init__(self, response):
self.response = response
self.queries = []
def inquire(self, query):
self.queries.append(query)
return self.response
def test_rest_recovery_uses_shared_settlement_callback_and_dedup_identity():
transport = FakeTransport(
{"rt_cd": "0", "output1": [{
"odno": "B1", "exec_id": "E1", "ccld_qty": "1",
"ccld_unpr": "101.25", "ccld_time": "20260906150000",
}]}
)
dedup = ExecutionEventDeduplicator()
delivered = []
def settle(report):
if dedup.accept(report):
pass
delivered.append(report)
return "SETTLED"
return "DUPLICATE"
service = LiveExecutionRecoveryService(
transport=transport,
adapter=KISFuturesExecutionRecoveryAdapter(),
correlation_provider=FakeCorrelationProvider(),
on_report=settle,
)
query = KISExecutionRecoveryQuery("12345678", "03", "20260906", "20260906")
assert service.recover(query) == ("SETTLED",)
assert service.recover(query) == ("DUPLICATE",)
assert len(delivered) == 1
assert delivered[0].client_order_id == "C1"
assert delivered[0].execution_price == Decimal("101.25")
def test_realtime_and_rest_same_execution_identity_settles_once():
dedup = ExecutionEventDeduplicator()
rest = ExecutionReport(
client_order_id="C1", broker_order_id="B1", execution_id="E1",
status="PARTIALLY_FILLED", filled_quantity=1, remaining_quantity=1,
execution_price=Decimal("101.25"), execution_timestamp=None,
)
realtime = ExecutionReport(
client_order_id="C1", broker_order_id="B1", execution_id="E1",
status="PARTIALLY_FILLED", filled_quantity=1, remaining_quantity=1,
execution_price=Decimal("101.25"), execution_timestamp=None,
)
assert dedup.accept(realtime) is True
assert dedup.accept(rest) is False
"""
