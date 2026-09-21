from datetime import datetime
from decimal import Decimal

import pytest

from contracts.types import DataQuality, ExecutionReport
from environments.virtual.execution.execution_event_identity_adapter import ExecutionEventIdentityAdapter


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
        source_freshness=DataQuality(is_fresh=True, is_complete=True, source_available=True),
    )


def test_execution_id_and_client_order_id_are_preserved_without_reconstruction():
    identity = ExecutionEventIdentityAdapter().identify(report())
    assert identity.execution_id == "EXEC-001"
    assert identity.client_order_id == "ORD-001"


def test_missing_execution_id_fails_closed():
    with pytest.raises(ValueError, match="EXECUTION_EVENT_ID_REQUIRED"):
        ExecutionEventIdentityAdapter().identify(report(execution_id=None))


def test_missing_client_order_id_fails_closed():
    with pytest.raises(ValueError, match="EXECUTION_EVENT_CLIENT_ORDER_ID_REQUIRED"):
        ExecutionEventIdentityAdapter().identify(report(client_order_id=""))
