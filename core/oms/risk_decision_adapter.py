from dataclasses import replace
from typing import Protocol

from core.oms.position_execution_policy import (
    PositionExecutionDecision,
    PositionExecutionRequest,
    PositionExecutionPolicyError,
)


class RiskDecisionLike(Protocol):
    decision: str
    is_approved: bool
    approved_qty: int
    reduced_command: object | None
    rejection_reason: str | None


class RiskDecisionMappingError(PositionExecutionPolicyError):
    pass


def apply_risk_decision(
    decision: PositionExecutionDecision,
    risk_result: RiskDecisionLike,
) -> PositionExecutionDecision:
    """Apply authoritative Risk result without inventing execution semantics."""
    status = str(risk_result.decision).upper()

    if status == "DENY" or not risk_result.is_approved:
        raise RiskDecisionMappingError(
            risk_result.rejection_reason or "ORDER_DENIED_BY_RISK"
        )

    if status == "ALLOW":
        qty = int(risk_result.approved_qty)
    elif status == "REDUCE":
        reduced = getattr(risk_result, "reduced_command", None)
        reduced_qty = getattr(reduced, "qty", None) if reduced is not None else None
        if reduced_qty is None:
            raise RiskDecisionMappingError("REDUCED_QUANTITY_REQUIRED")
        if int(risk_result.approved_qty) != int(reduced_qty):
            raise RiskDecisionMappingError("RISK_QUANTITY_PROVENANCE_MISMATCH")
        qty = int(reduced_qty)
    else:
        raise RiskDecisionMappingError(f"UNKNOWN_RISK_DECISION: {status}")

    if qty <= 0:
        raise RiskDecisionMappingError("APPROVED_QUANTITY_REQUIRED")

    return replace(decision, approved_quantity=qty)
