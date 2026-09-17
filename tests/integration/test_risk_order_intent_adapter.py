from dataclasses import dataclass
from decimal import Decimal

import pytest

from core.oms.position_execution_policy import PositionExecutionDecision
from core.oms.risk_order_intent_adapter import (
RiskOrderIntentMappingError,
build_order_intent_execution_input,
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


def decision():
    return PositionExecutionDecision(
        client_order_id="ORD-1",
        approved_quantity=5,
        requested_price=Decimal("1.25"),
        order_type="LIMIT",
        order_purpose="ENTRY",
        asset_type="OPTION",
        track_id="track1",
        tag_id="tail-defense",
    )


def test_allow_maps_authoritative_quantity_and_preserves_semantics():
    result = build_order_intent_execution_input(
        decision(), RiskResult("ALLOW", True, 5)
    )
    assert result.quantity == 5
    assert result.requested_price == Decimal("1.25")
    assert result.order_type == "LIMIT"
    assert result.order_purpose == "ENTRY"
    assert result.asset_type == "OPTION"
    assert result.track_id == "track1"
    assert result.tag_id == "tail-defense"


def test_reduce_maps_reduced_command_quantity():
    result = build_order_intent_execution_input(
        decision(), RiskResult("REDUCE", True, 3, ReducedCommand(3))
    )
    assert result.quantity == 3


def test_reduce_provenance_mismatch_fails_closed():
    with pytest.raises(RiskOrderIntentMappingError, match="PROVENANCE"):
        build_order_intent_execution_input(
            decision(), RiskResult("REDUCE", True, 4, ReducedCommand(3))
        )


def test_deny_does_not_build_execution_input():
    with pytest.raises(RiskOrderIntentMappingError, match="LIMIT"):
        build_order_intent_execution_input(
            decision(), RiskResult("DENY", False, 0, rejection_reason="LIMIT")
        )


def test_unknown_risk_decision_fails_closed():
    with pytest.raises(RiskOrderIntentMappingError, match="UNKNOWN_RISK_DECISION"):
        build_order_intent_execution_input(
            decision(), RiskResult("UNKNOWN", True, 5)
        )
