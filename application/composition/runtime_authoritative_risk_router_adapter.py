from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from core.position.position_aggregate import PositionAggregateSource
from core.risk.risk_input import RiskAccountInput
from core.risk.risk_position import position_manager_to_risk_input
from core.runtime.reference_execution_pipeline import CanonicalRiskCommandAdapter, ReferenceExecutionResult
from core.oms.risk_approved_broker_command_adapter import project_risk_effective_quantity
from shared.contracts.canonical import CanonicalOrderCommand
from contracts.market_data_freshness import FreshnessVerdict, permits_risk_increasing_order

@dataclass(frozen=True)
class RiskRouterContext:
    account_snapshot: Any
    position_source: PositionAggregateSource
    order_router: Any
    broker_command: Any = None

def account_snapshot_to_risk_input(source: Any) -> RiskAccountInput:
    balances = getattr(source, "balances", None)
    if balances is not None:
        return RiskAccountInput(Decimal(balances["cash"]), Decimal(balances["realized_pnl"]), Decimal(balances.get("margin_used", 0)), Decimal(balances.get("available_cash", balances["cash"])))
    return RiskAccountInput(Decimal(str(source.total_balance)), Decimal(str(source.realized_pnl)), Decimal(str(source.used_margin)), Decimal(str(source.free_margin)))

def route_from_runtime_authoritative_sources(command: CanonicalOrderCommand, *, risk_gate: Any, context: RiskRouterContext, sensor_snapshot: Any = None, allow_reduction: bool = False, freshness_verdict: FreshnessVerdict | None = None) -> ReferenceExecutionResult:
    # No broker routing is permitted without an explicit, identity-matched FRESH verdict.
    # The current KIS time-only fields do not yet establish absolute source-time semantics.
    if not permits_risk_increasing_order(freshness_verdict):
        reason = "MARKET_DATA_FRESHNESS_VERDICT_REQUIRED" if freshness_verdict is None else f"MARKET_DATA_FRESHNESS_{freshness_verdict.status.value}:{freshness_verdict.reason}"
        return ReferenceExecutionResult(False, "DENY", False, None, reason)
    if (
        not command.instrument_id
        or not command.symbol
        or freshness_verdict.instrument_id != command.instrument_id
        or freshness_verdict.symbol != command.symbol
    ):
        return ReferenceExecutionResult(False, "DENY", False, None, "MARKET_DATA_FRESHNESS_COMMAND_IDENTITY_MISMATCH")
    adapted = CanonicalRiskCommandAdapter.from_command(command)
    approved, token, rejection_reason = risk_gate.admit_order(adapted, account_snapshot_to_risk_input(context.account_snapshot), position_manager_to_risk_input(context.position_source), sensor_snapshot, allow_reduction)
    result = risk_gate.last_evaluation_result
    if not approved or result is None:
        return ReferenceExecutionResult(False, getattr(result, "decision", "DENY"), False, None, rejection_reason or getattr(result, "rejection_reason", None))
    if token is None:
        raise RuntimeError("RISK_APPROVAL_TOKEN_REQUIRED")
    effective = result.reduced_command if result.decision == "REDUCE" and result.reduced_command is not None else adapted
    routed_command = project_risk_effective_quantity(original=context.broker_command, effective=effective) if context.broker_command is not None else effective
    context.order_router.register_and_route(routed_command, token, freshness_verdict=freshness_verdict)
    return ReferenceExecutionResult(True, result.decision, True, effective)
