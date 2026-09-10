from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from contracts.types import ExecutionLeg, MultiLegExecutionPlan


def build_pair_plan(
# *,
    group_id: str,
    strategy_id: str,
    purpose: str,
    put_strike: Decimal,
    call_strike: Decimal,
    put_quantity: int,
    call_quantity: int,
    side: str = "BUY",
) -> MultiLegExecutionPlan:
    """Build a typed CALL/PUT pair without encoding submission policy."""
    return MultiLegExecutionPlan(
        group_id=group_id,
        strategy_id=strategy_id,
        purpose=purpose,
        legs=(
            ExecutionLeg("put", side, put_quantity, "PUT", put_strike),
            ExecutionLeg("call", side, call_quantity, "CALL", call_strike),
        ),
    )


def build_trap_plan(
# *,
    group_id: str,
    strategy_id: str,
    purpose: str,
    short_put: Decimal,
    short_call: Decimal,
    long_put: Decimal,
    long_call: Decimal,
    quantity: int = 1,
) -> MultiLegExecutionPlan:
    """Build Track2's four-leg trap while preserving side and strike per leg."""
    return MultiLegExecutionPlan(
        group_id=group_id,
        strategy_id=strategy_id,
        purpose=purpose,
        legs=(
            ExecutionLeg("short_put", "SELL", quantity, "PUT", short_put),
            ExecutionLeg("short_call", "SELL", quantity, "CALL", short_call),
            ExecutionLeg("long_put", "BUY", quantity, "PUT", long_put),
            ExecutionLeg("long_call", "BUY", quantity, "CALL", long_call),
        ),
    )
