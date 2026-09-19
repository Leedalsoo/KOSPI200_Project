from __future__ import annotations

from contracts.futures_identity_source_port import FuturesInstrumentIdentity
from contracts.types import ExecutionLeg, MultiLegExecutionPlan


class Track3FuturesExecutionPlanAdapter:
    """Translate an approved Track3 Futures decision into one typed execution leg."""

    def build_plan(
        self, *, strategy_id: str, group_id: str, side: str,
        quantity: int, identity: FuturesInstrumentIdentity,
    ) -> MultiLegExecutionPlan:
        if not strategy_id.strip() or not group_id.strip():
            raise ValueError("TRACK3_EXECUTION_CONTEXT_REQUIRED")
        if side not in {"BUY", "SELL"} or quantity <= 0:
            raise ValueError("TRACK3_EXECUTION_ORDER_REQUIRED")
        if identity is None:
            raise ValueError("TRACK3_FUTURES_IDENTITY_REQUIRED")
        return MultiLegExecutionPlan(
            group_id=group_id,
            strategy_id=strategy_id,
            purpose="TRACK3_FUTURES_EXECUTION",
            legs=(ExecutionLeg(leg_id="FUTURES", side=side, quantity=quantity),),
        )
