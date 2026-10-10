"""Discriminated Strategy execution-plan contract for single and multi-leg intents."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from contracts.types import MultiLegExecutionPlan
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal


class ExecutionPlanKind(str, Enum):
    SINGLE_ORDER = "SINGLE_ORDER"
    MULTI_LEG = "MULTI_LEG"


@dataclass(frozen=True)
class StrategyExecutionPlan:
    """One standard output shape for any approved strategy execution intent."""

    signal_id: str
    strategy_id: str
    kind: ExecutionPlanKind
    single_order_proposal: StrategyExecutionProposal | None = None
    multi_leg_plan: MultiLegExecutionPlan | None = None
    strategy_code_version: str | None = None
    strategy_config_version: str | None = None
    strategy_config_hash: str | None = None

    def __post_init__(self) -> None:
        if not self.signal_id.strip():
            raise ValueError("STRATEGY_EXECUTION_PLAN_SIGNAL_ID_REQUIRED")
        if not self.strategy_id.strip():
            raise ValueError("STRATEGY_EXECUTION_PLAN_STRATEGY_ID_REQUIRED")
        kind = ExecutionPlanKind(self.kind)
        object.__setattr__(self, "kind", kind)
        if self.strategy_config_version is not None and (
            self.strategy_code_version is None
            or self.strategy_config_hash is None
            or len(self.strategy_config_hash) != 64
        ):
            raise ValueError("STRATEGY_EXECUTION_PLAN_CONFIG_PROVENANCE_INVALID")
        if self.strategy_config_hash is not None and self.strategy_config_version is None:
            raise ValueError("STRATEGY_EXECUTION_PLAN_CONFIG_VERSION_REQUIRED")
        if kind is ExecutionPlanKind.SINGLE_ORDER:
            if self.single_order_proposal is None or self.multi_leg_plan is not None:
                raise ValueError("SINGLE_ORDER_PLAN_SHAPE_INVALID")
            proposal_strategy = str(getattr(self.single_order_proposal, "track_id", "") or "")
            if proposal_strategy and proposal_strategy != self.strategy_id:
                raise ValueError("SINGLE_ORDER_PLAN_STRATEGY_ID_MISMATCH")
        else:
            if self.multi_leg_plan is None or self.single_order_proposal is not None:
                raise ValueError("MULTI_LEG_PLAN_SHAPE_INVALID")
            if self.multi_leg_plan.strategy_id != self.strategy_id:
                raise ValueError("MULTI_LEG_PLAN_STRATEGY_ID_MISMATCH")
