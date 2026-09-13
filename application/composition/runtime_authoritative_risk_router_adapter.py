from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from core.position.position_aggregate import PositionAggregateSource
from core.risk.risk_input import RiskAccountInput
from core.risk.risk_position import position_manager_to_risk_input
from core.runtime.reference_execution_pipeline import CanonicalRiskCommandAdapter, ReferenceExecutionResult
from shared.contracts.canonical import CanonicalOrderCommand


@dataclass(frozen=True)
class RiskRouterContext:
    account_snapshot: Any
    position_source: PositionAggregateSource
    order_router: Any


def _account_input(source: Any) -> RiskAccountInput:
    balances = getattr(source, "balances", None)
    if balances is not None:
        return RiskAccountInput(
            total_balance=Decimal(balances["cash"]),
            realized_pnl=Decimal(balances["realized_pnl"]),
            used_margin=Decimal(balances.get("margin_used", 0)),
            free_margin=Decimal(balances.get("available_cash", balances["cash"])),
        )
    return RiskAccountInput(
        total_balance=Decimal(str(source.total_balance)),
        realized_pnl=Decimal(str(source.realized_pnl)),
        used_margin=Decimal(str(source.used_margin)),
        free_margin=Decimal(str(source.free_margin)),
    )


def route_from_runtime_authoritative_sources(
    command: CanonicalOrderCommand,
    *,
    risk_gate: Any,
    context: RiskRouterContext,
    sensor_snapshot: Any = None,
    allow_reduction: bool = False,
) -> ReferenceExecutionResult:
    adapted = CanonicalRiskCommandAdapter.from_command(command)
    account = _account_input(context.account_snapshot)
    positions = position_manager_to_risk_input(context.position_source)
    approved, token, rejection_reason = risk_gate.admit_order(
        adapted, account, positions, sensor_snapshot, allow_reduction
    )
    result = risk_gate.last_evaluation_result
    if not approved or result is None:
        return ReferenceExecutionResult(
            approved=False,
            decision=getattr(result, "decision", "DENY"),
            routed=False,
            effective_command=None,
            rejection_reason=rejection_reason or getattr(result, "rejection_reason", None),
        )
    if token is None:
        raise RuntimeError("RISK_APPROVAL_TOKEN_REQUIRED")
    effective = (
        result.reduced_command
        if result.decision == "REDUCE" and result.reduced_command is not None
        else adapted
    )
    try:
        context.order_router.register_and_route(effective, token)
    except TypeError:
        context.order_router.register_and_route(effective)
    return ReferenceExecutionResult(
        approved=True,
        decision=result.decision,
        routed=True,
        effective_command=effective,
    )
