"""Test Execution Event Deduplicator — test specification.

from datetime import datetime
from decimal import Decimal
import pytest
from contracts.types import ExecutionReport
from environments.virtual.execution.execution_event_deduplicator import (
ExecutionEventDeduplicator,
)
def report(execution_id="EXEC-001", client_order_id="ORD-001"):
return ExecutionReport(
client_order_id=client_order_id,
broker_order_id="BRK-001",
execution_id=execution_id,
status="FILLED",
filled_quantity=3,
remaining_quantity=0,
execution_price=Decimal("101.5"),
execution_timestamp=datetime(2026, 9, 5),
)
def test_first_execution_event_is_accepted():
assert ExecutionEventDeduplicator().accept(report()) is True
def test_same_execution_id_is_accepted_only_once():
gate = ExecutionEventDeduplicator()
assert gate.accept(report("EXEC-001")) is True
assert gate.accept(report("EXEC-001", "ORD-002")) is False
def test_distinct_execution_ids_are_independent():
gate = ExecutionEventDeduplicator()
assert gate.accept(report("EXEC-001")) is True
assert gate.accept(report("EXEC-002", "ORD-002")) is True
def test_missing_execution_id_fails_closed():
with pytest.raises(ValueError, match="EXECUTION_EVENT_ID_REQUIRED"):
pass
ExecutionEventDeduplicator().accept(report(None))
"""
