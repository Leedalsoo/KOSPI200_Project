from __future__ import annotations

from contracts.futures_identity_source_port import FuturesIdentitySourcePort, FuturesInstrumentIdentity, require_futures_identity
from contracts.types import ExecutionLeg, MultiLegExecutionPlan


class Track3MultiLegExecutionPlanAdapter:
    """Build the authoritative Track3 futures + hedge execution plan."""

    STRATEGY_ID = "Strategy_3_StatArb"

    def build_plan(self, *, strategy_id: str, group_id: str, side: str, quantity: int,
                   identity: FuturesInstrumentIdentity | None,
                   hedge_identity_source: FuturesIdentitySourcePort | None) -> MultiLegExecutionPlan:
        if strategy_id != self.STRATEGY_ID:
            raise ValueError("TRACK3_STRATEGY_REQUIRED")
        if not group_id.strip():
            raise ValueError("TRACK3_GROUP_ID_REQUIRED")
        if side not in {"BUY", "SELL"} or quantity <= 0:
            raise ValueError("TRACK3_EXECUTION_ORDER_REQUIRED")
        if not isinstance(identity, FuturesInstrumentIdentity):
            raise ValueError("TRACK3_FUTURES_IDENTITY_REQUIRED")
        hedge_identity = require_futures_identity(hedge_identity_source)
        if hedge_identity != identity:
            raise ValueError("TRACK3_HEDGE_IDENTITY_MISMATCH")
        hedge_side = "SELL" if side == "BUY" else "BUY"
        return MultiLegExecutionPlan(
            group_id=group_id,
            strategy_id=strategy_id,
            purpose="TRACK3_STAT_ARB_FUTURES_HEDGE",
            legs=(
                ExecutionLeg("FUTURES", side, quantity, position_role="NONE"),
                ExecutionLeg("HEDGE", hedge_side, quantity, position_role="NONE"),
            ),
        )
