from decimal import Decimal
from types import SimpleNamespace

import pytest

from contracts.analytics import AnalyticsStatus
from core.strategy.strategy_execution_proposal import StrategyExecutionProposal
from core.strategy.track5_gap_divergence import Track5GapDivergence, Track5State


def test_retired_s5_entry_policy_is_blocked_even_when_old_runtime_flags_are_true():
    strategy = Track5GapDivergence(
        runtime_config_verified=True,
        risk_limits_available=True,
    )
    assert strategy.CURRENT_EXECUTION_POLICY_APPROVED is False
    assert strategy.evaluate_gap(SimpleNamespace(), None) == ()
    assert strategy.last_block_reason == "TRACK5_CURRENT_EXECUTION_POLICY_UNAPPROVED"


def test_stale_option_buy_proposal_cannot_bypass_s5_entry_policy_gate():
    strategy = Track5GapDivergence(
        runtime_config_verified=True,
        risk_limits_available=True,
    )
    proposal = StrategyExecutionProposal(
        proposed_quantity=2,
        asset_type="OPTION",
        side="BUY",
        track_id="track5_gap_divergence",
        tag_id="GAP_DIVERGENCE_ENTRY_OPTION",
        option_type="CALL",
        strike=Decimal("885"),
    )
    with pytest.raises(ValueError, match="TRACK5_CURRENT_EXECUTION_POLICY_UNAPPROVED"):
        strategy.build_execution_plan("s5-stale-entry", proposal=proposal)


def test_legacy_open_position_option_exit_path_remains_available():
    strategy = Track5GapDivergence(
        runtime_config_verified=True,
        risk_limits_available=True,
    )
    strategy.state = Track5State(
        is_active=True,
        direction="SHORT",
        entry_price=Decimal("100"),
        target_price=Decimal("95"),
        stop_loss_price=Decimal("110"),
        open_ticks=2,
        peak_pnl=Decimal("3"),
        expected_move_pts=Decimal("2"),
        gap_extreme_price=Decimal("102"),
        option_type="CALL",
        selected_strike=Decimal("885"),
        futures_closed=True,
    )
    signals = strategy.evaluate_mean_reversion(Decimal("95"))
    assert len(signals) == 1
    proposal = signals[0].execution_proposal
    assert proposal.side == "SELL"
    assert proposal.asset_type == "OPTION"
    assert proposal.tag_id == "GAP_DIVERGENCE_OPTION_SECOND_EXIT"

    plan = strategy.build_execution_plan("s5-existing-position", proposal=proposal)
    assert plan.purpose == "TRACK5_GAP_HEDGE_OPTION_EXIT"
    assert plan.legs[0].side == "SELL"


def test_legacy_open_position_futures_close_path_remains_available():
    strategy = Track5GapDivergence(
        runtime_config_verified=True,
        risk_limits_available=True,
    )
    strategy.state = Track5State(
        is_active=True,
        direction="SHORT",
        entry_price=Decimal("100"),
        target_price=Decimal("95"),
        stop_loss_price=Decimal("110"),
        expected_move_pts=Decimal("2"),
        gap_extreme_price=Decimal("102"),
        option_type="CALL",
        selected_strike=Decimal("885"),
        futures_side="SELL",
        futures_closed=False,
        futures_close_requested=True,
    )
    proposal = StrategyExecutionProposal(
        proposed_quantity=5,
        asset_type="FUTURES",
        side="BUY",
        track_id="track5_gap_divergence",
        tag_id="GAP_DIVERGENCE_FUTURES_FIRST_EXIT",
    )
    plan = strategy.build_execution_plan("s5-existing-position", proposal=proposal)
    assert plan.purpose == "TRACK5_GAP_HEDGE_FUTURES_EXIT"
    assert plan.legs[0].side == "BUY"


def test_legacy_futures_close_requires_explicit_pending_close_state():
    strategy = Track5GapDivergence(
        runtime_config_verified=True,
        risk_limits_available=True,
    )
    strategy.state = Track5State(
        is_active=True,
        direction="SHORT",
        entry_price=Decimal("100"),
        futures_side="SELL",
        futures_closed=False,
        futures_close_requested=False,
    )
    proposal = StrategyExecutionProposal(
        proposed_quantity=5,
        asset_type="FUTURES",
        side="BUY",
        track_id="track5_gap_divergence",
        tag_id="GAP_DIVERGENCE_FUTURES_FIRST_EXIT",
    )
    with pytest.raises(ValueError, match="TRACK5_FUTURES_CLOSE_NOT_REQUESTED_OR_UNSUPPORTED"):
        strategy.build_execution_plan("s5-no-pending-close", proposal=proposal)
