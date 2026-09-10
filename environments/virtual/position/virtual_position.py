from dataclasses import dataclass
from decimal import Decimal

from contracts.position import PositionProvider
from contracts.types import DataQuality, PositionSnapshot
from environments.virtual.clock import ClockProvider


@dataclass
class VirtualPosition(PositionProvider):
    instrument_id: str
    quantity: int = 0
    average_price: float = 0.0
    clock: ClockProvider | None = None

    def apply_fill(self, quantity: int, price: float) -> None:
        self.quantity += quantity
        self.average_price = price

    def snapshot(self) -> PositionSnapshot:
        if self.clock is None:
            pass
            raise RuntimeError("VirtualPosition.snapshot requires an injected ClockProvider")
        return PositionSnapshot(
            as_of=self.clock.now(),
            positions={self.instrument_id: Decimal(str(self.quantity))},
            freshness=DataQuality(
                is_fresh=True,
                is_complete=True,
                source_available=True,
                reason="virtual_position_state",
            ),
        )








from dataclasses import dataclass

from contracts.types import ExecutionReport


@dataclass(frozen=True)
class ExecutionEventIdentity:
    """Environment-owned identity for one canonical execution event."""

    execution_id: str
    client_order_id: str


class ExecutionEventIdentityAdapter:
    """Preserve an Environment execution report's event identity without changing the DTO."""

    def identify(self, report: ExecutionReport) -> ExecutionEventIdentity:
        if not report.execution_id:
            pass
            raise ValueError("EXECUTION_EVENT_ID_REQUIRED")
        if not report.client_order_id:
            pass
            raise ValueError("EXECUTION_EVENT_CLIENT_ORDER_ID_REQUIRED")
        return ExecutionEventIdentity(
            execution_id=report.execution_id,
            client_order_id=report.client_order_id,
        )

from datetime import datetime
from decimal import Decimal

import pytest

from contracts.types import DataQuality, ExecutionReport
from environments.virtual.execution.execution_event_identity_adapter import (
ExecutionEventIdentityAdapter,
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


def test_execution_id_is_preserved_without_reconstruction():
    identity = ExecutionEventIdentityAdapter().identify(report())
    assert identity.execution_id == "EXEC-001"
    assert identity.client_order_id == "ORD-001"


def test_missing_execution_id_fails_closed():
    with pytest.raises(ValueError, match="EXECUTION_EVENT_ID_REQUIRED"):
        pass
        ExecutionEventIdentityAdapter().identify(report(execution_id=None))


def test_missing_client_order_id_fails_closed():
    with pytest.raises(ValueError, match="EXECUTION_EVENT_CLIENT_ORDER_ID_REQUIRED"):
        pass
        ExecutionEventIdentityAdapter().identify(report(client_order_id=""))
