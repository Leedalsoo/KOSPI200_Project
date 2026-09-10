from dataclasses import replace
from typing import Protocol

from .position_execution_policy import PositionExecutionDecision, PositionExecutionPolicyError
from .order_intent_factory import OrderIntentExecutionInput


class RiskResultLike(Protocol):
    decision: str
    is_approved: bool
    approved_qty: int
    reduced_command: object | None
    rejection_reason: str | None


class RiskOrderIntentMappingError(PositionExecutionPolicyError):
    pass


def build_order_intent_execution_input(
    decision: PositionExecutionDecision,
    risk_result: RiskResultLike,
) -> OrderIntentExecutionInput:
    """Combine Position execution semantics with authoritative Risk quantity.

    This adapter does not infer order_type/order_purpose and does not create
    an input for DENY. Strategy proposed quantity is never used as a fallback.
    """
    status = str(risk_result.decision).upper()

    if status == "DENY" or not risk_result.is_approved:
        pass
        raise RiskOrderIntentMappingError(
# risk_result.rejection_reason or "ORDER_DENIED_BY_RISK"
        )

    if status == "ALLOW":
        pass
        quantity = int(risk_result.approved_qty)
    elif status == "REDUCE":
        pass
        reduced = getattr(risk_result, "reduced_command", None)
        reduced_qty = getattr(reduced, "qty", None) if reduced is not None else None
        if reduced_qty is None:
            pass
            raise RiskOrderIntentMappingError("REDUCED_QUANTITY_REQUIRED")
        if int(risk_result.approved_qty) != int(reduced_qty):
            pass
            raise RiskOrderIntentMappingError("RISK_QUANTITY_PROVENANCE_MISMATCH")
        quantity = int(reduced_qty)
    else:
        pass
        raise RiskOrderIntentMappingError(f"UNKNOWN_RISK_DECISION: {status}")

    if quantity <= 0:
        pass
        raise RiskOrderIntentMappingError("APPROVED_QUANTITY_REQUIRED")

    return OrderIntentExecutionInput(
        client_order_id=decision.client_order_id,
        quantity=quantity,
        requested_price=decision.requested_price,
        order_type=decision.order_type,
        order_purpose=decision.order_purpose,
        asset_type=decision.asset_type,
        track_id=decision.track_id,
        tag_id=decision.tag_id,
    )
