"""Multi-leg execution plan helper adapter.

Re-exports core.oms.multi_leg_plan functions for strategy layer compatibility.
Source of design: Notion OptionProject/core/oms/multi_leg_plan.py
"""
from __future__ import annotations

from core.oms.multi_leg_plan import (
    ExecutionLeg,
    MultiLegExecutionPlan,
    build_pair_plan,
    build_trap_plan,
)

__all__ = [
    "ExecutionLeg",
    "MultiLegExecutionPlan",
    "build_pair_plan",
    "build_trap_plan",
]
