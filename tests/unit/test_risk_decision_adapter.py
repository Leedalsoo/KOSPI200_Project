from dataclasses import dataclass
from decimal import Decimal
import pytest

from option_program.core.oms.position_execution_policy import PositionExecutionDecision
from option_program.core.oms.risk_decision_adapter import (
RiskDecisionMappingError,
apply_risk_decision,
)


@dataclass
class ReducedCommand:
    qty: int


@dataclass
class RiskResult:
    decision: str
    is_approved: bool
    approved_qty: int
    reduced_command: object | None = None
    rejection_reason: str | None = None


def base_decision():
    return PositionExecutionDecision(
        client_order_id="ORD-1",
        approved_quantity=5,
        requested_price=Decimal("1.25"),
        order_type="LIMIT",
        order_purpose="ENTRY",
        asset_type="OPTION",
        track_id="Track1",
        tag_id="Track1",
    )


def test_allow_uses_approved_quantity_and_preserves_execution_semantics():
    result = apply_risk_decision(
        base_decision(), RiskResult("ALLOW", True, 5)
    )
    assert result.approved_quantity == 5
    assert result.order_type == "LIMIT"
    assert result.order_purpose == "ENTRY"
    assert result.requested_price == Decimal("1.25")


def test_reduce_uses_reduced_command_quantity():
    result = apply_risk_decision(
        base_decision(), RiskResult("REDUCE", True, 3, ReducedCommand(3))
    )
    assert result.approved_quantity == 3


def test_reduce_rejects_quantity_provenance_mismatch():
    with pytest.raises(RiskDecisionMappingError, match="PROVENANCE"):
        pass
        apply_risk_decision(
            base_decision(), RiskResult("REDUCE", True, 4, ReducedCommand(3))
        )


def test_deny_does_not_create_order_intent():
    with pytest.raises(RiskDecisionMappingError, match="LIMIT"):
        pass
        apply_risk_decision(
            base_decision(), RiskResult("DENY", False, 0, rejection_reason="LIMIT")
        )
