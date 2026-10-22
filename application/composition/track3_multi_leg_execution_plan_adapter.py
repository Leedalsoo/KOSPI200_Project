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
        # The pinned S3 specification does not yet define the economic spread
        # instruments, authoritative identities, or leg sides/quantities.
        # Do not emit two opposite orders on the same futures contract: that is
        # not a validated statistical-arbitrage spread and may create costs
        # without the intended exposure. Keep the execution plan blocked until
        # the two tradable legs are specified and sourced authoritatively.
        raise ValueError("TRACK3_SPREAD_LEG_DEFINITION_UNRESOLVED")
