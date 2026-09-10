from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


class PositionExecutionPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class PositionExecutionRequest:
    """Authoritative inputs already produced upstream; no synthetic defaults."""
    client_order_id: str
    proposed_quantity: int
    requested_price: Decimal | None
    asset_type: str
    track_id: str | None = None
    tag_id: str | None = None


@dataclass(frozen=True)
class PositionExecutionDecision:
    """Execution semantics owned by Position/Risk/Order Policy boundary."""
    client_order_id: str
    approved_quantity: int
    requested_price: Decimal | None
    order_type: str
    order_purpose: str
    asset_type: str
    track_id: str | None = None
    tag_id: str | None = None


class PositionExecutionPolicy(Protocol):
    def decide(
# self,
        request: PositionExecutionRequest,
    ) -> PositionExecutionDecision:
        ...
