import pytest

from application.composition.track3_multi_leg_execution_plan_adapter import (
    Track3MultiLegExecutionPlanAdapter,
)


def test_track3_execution_plan_stays_blocked_until_tradable_spread_legs_are_defined():
    adapter = Track3MultiLegExecutionPlanAdapter()

    with pytest.raises(ValueError, match="TRACK3_SPREAD_LEG_DEFINITION_UNRESOLVED"):
        adapter.build_plan(
            strategy_id="Strategy_3_StatArb",
            group_id="s3-unresolved-spread",
            side="BUY",
            quantity=1,
            identity=None,
            hedge_identity_source=None,
        )
