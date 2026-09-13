from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from core.position.position_aggregate import PositionAggregateSource
from core.position.position_aggregate_risk_adapter import position_aggregate_to_risk_input
from core.risk.risk_input import account_snapshot_to_risk_input
from core.runtime.reference_execution_pipeline import CanonicalRiskCommandAdapter, ReferenceExecutionResult
from core.oms.risk_approved_broker_command_adapter import project_risk_effective_quantity
from shared.contracts.canonical import CanonicalOrderCommand

@dataclass(frozen=True)
class RiskRouterContext:
    account_snapshot: Any
    position_source: PositionAggregateSource
    order_router: Any
    broker_command: Any = None

def route_from_runtime_authoritative_sources(command: CanonicalOrderCommand, *, risk_gate: Any, context: RiskRouterContext, sensor_snapshot: Any = None, allow_reduction: bool = False) -> ReferenceExecutionResult:
    adapted = CanonicalRiskCommandAdapter.from_command(command)
    account = account_snapshot_to_risk_input(context.account_snapshot)
    positions = position_aggregate_to_risk_input(context.position_source)
    approved, token, rejection_reason = risk_gate.admit_order(adapted, account, positions, sensor_snapshot, allow_reduction)
    result = risk_gate.last_evaluation_result
    if not approved or result is None:
        return ReferenceExecutionResult(False, getattr(result, 'decision', 'DENY'), False, None, rejection_reason or getattr(result, 'rejection_reason', None))
    effective = result.reduced_command if result.decision == 'REDUCE' and result.reduced_command is not None else adapted
    if token is None:
        raise RuntimeError("RISK_APPROVAL_TOKEN_REQUIRED")
    routed_command = project_risk_effective_quantity(original=context.broker_command, effective=effective) if context.broker_command is not None else effective
    return ReferenceExecutionResult(True, result.decision, True, routed_command)
