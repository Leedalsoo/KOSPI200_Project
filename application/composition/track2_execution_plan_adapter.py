"""Track2 Decision -> multi-leg execution-plan boundary."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from contracts.types import MultiLegExecutionPlan


class Track2ExecutionPlanAdapter:
    """Convert an approved Track2 entry decision into its strategy-owned plan."""

    STRATEGY_ID = "track2_asymmetric_trap"

    def build_plan(
        self,
        *,
        approved_signal: Any,
        strategy: Any,
        current_atm: Decimal,
        active_vol: float,
        base_vol: float,
        group_id: str,
    ) -> MultiLegExecutionPlan:
        if getattr(approved_signal, "track_id", "") != self.STRATEGY_ID:
            raise ValueError("TRACK2_DECISION_STRATEGY_MISMATCH")
        if getattr(approved_signal, "reason", "") != "ASYMMETRIC_TRAP_ENTRY":
            raise ValueError("TRACK2_ENTRY_DECISION_REQUIRED")
        if getattr(strategy, "strategy_id", "") != self.STRATEGY_ID:
            raise ValueError("TRACK2_STRATEGY_REQUIRED")
        if not group_id.strip():
            raise ValueError("TRACK2_GROUP_ID_REQUIRED")

        plan = strategy.build_execution_plan(
            group_id=group_id,
            current_atm=current_atm,
            active_vol=active_vol,
            base_vol=base_vol,
        )
        if plan.strategy_id != self.STRATEGY_ID:
            raise ValueError("TRACK2_PLAN_STRATEGY_MISMATCH")
        if len(plan.legs) != 4:
            raise ValueError("TRACK2_FOUR_LEG_PLAN_REQUIRED")
        return plan
