from decimal import Decimal

import pytest

from core.strategy.strategy_execution_proposal import StrategyExecutionProposal
from core.strategy.track5_gap_divergence import Track5GapDivergence


def _entry_proposal() -> StrategyExecutionProposal:
    return StrategyExecutionProposal(
        proposed_quantity=2,
        asset_type="OPTION",
        side="BUY",
        track_id="track5_gap_divergence",
        tag_id="GAP_DIVERGENCE_ENTRY_OPTION",
        option_type="CALL",
        strike=Decimal("500"),
    )


def test_track5_new_entry_plan_is_two_options_without_futures() -> None:
    strategy = Track5GapDivergence(
        runtime_config_verified=True, risk_limits_available=True
    )

    plan = strategy.build_execution_plan(
        group_id="s5-option-only",
        proposal=_entry_proposal(),
    )

    assert plan.purpose == "TRACK5_OPTION_ONLY_ENTRY"
    assert len(plan.legs) == 1
    assert plan.legs[0].leg_id == "OPTION_ENTRY"
    assert plan.legs[0].side == "BUY"
    assert plan.legs[0].quantity == 2
    assert plan.legs[0].option_type == "CALL"


def test_track5_entry_plan_blocks_unverified_config_and_risk() -> None:
    strategy = Track5GapDivergence()

    with pytest.raises(ValueError, match="TRACK5_CONFIG_OR_RISK_GATE_BLOCKED"):
        strategy.build_execution_plan(
            group_id="s5-blocked",
            proposal=_entry_proposal(),
        )


def test_track5_does_not_create_new_futures_order_from_option_only_state() -> None:
    strategy = Track5GapDivergence(
        runtime_config_verified=True, risk_limits_available=True
    )

    futures_proposal = StrategyExecutionProposal(
        proposed_quantity=5,
        asset_type="FUTURES",
        side="SELL",
        track_id="track5_gap_divergence",
        tag_id="LEGACY_FUTURES_ENTRY",
    )

    with pytest.raises(ValueError, match="TRACK5_NEW_FUTURES_ORDERS_DISABLED_BY_APPROVED_SPEC"):
        strategy.build_execution_plan(
            group_id="s5-no-new-futures",
            proposal=futures_proposal,
        )
