from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RiskApprovalToken:
    """Standard Core risk approval proof.

    The contract intentionally does not depend on Legacy shared contracts.
    """

    order_id: UUID
    timestamp_ns: int
    signature: str


@dataclass(frozen=True, slots=True)
class RiskEvaluationResult:
    """Authoritative result of a pre-trade risk evaluation."""

    is_approved: bool
    decision: str = "ALLOW"
    original_qty: int = 0
    approved_qty: int = 0
    rejection_reason: str | None = None
    required_margin: float = 0.0
    estimated_margin_ratio: float = 0.0
    token: RiskApprovalToken | None = None
    reduced_command: Any | None = None
