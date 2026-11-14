from decimal import Decimal
from types import SimpleNamespace

import pytest

from core.strategy.strategy_execution_proposal import StrategyExecutionProposal
from core.strategy.track5_gap_divergence import Track5GapDivergence, Track5State


def test_retired_s5_entry_policy_is_blocked_even_when_old_runtime_flags_are_true():
    strategy = Track5GapDivergence(
        runtime_config_verified=True,
        risk_limits_available=True,
    )
    assert strategy.CURRENT_EXECUTION_POLICY_APPROVED is False
    assert "MINI_FUTURES_QUANTITY" in strategy.CONFIGURABLE_PARAMETERS
    assert strategy.MINI_FUTURES_QUANTITY == 5  # compatibility only, not close sizing
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


def _active_legacy_strategy(**state_changes):
    state = Track5State(
        is_active=True,
        direction="SHORT",
        entry_price=Decimal("100"),
        target_price=Decimal("95"),
        stop_loss_price=Decimal("110"),
        open_ticks=2,
        peak_pnl=Decimal("0"),
        expected_move_pts=Decimal("2"),
        gap_extreme_price=Decimal("102"),
        option_type="CALL",
        selected_strike=Decimal("885"),
        futures_side="SELL",
        futures_closed=False,
    )
    return Track5GapDivergence(), Track5State(**{**state.__dict__, **state_changes})


def test_legacy_open_position_option_exit_emits_trigger_not_order_quantity():
    strategy, strategy.state = _active_legacy_strategy(futures_closed=True)
    signals = strategy.evaluate_mean_reversion(Decimal("95"))
    assert len(signals) == 1
    proposal = signals[0].execution_proposal
    assert proposal.side == "SELL"
    assert proposal.asset_type == "OPTION"
    assert proposal.proposed_quantity == strategy.EXIT_PROPOSAL_QUANTITY == 1
    assert proposal.tag_id == "GAP_DIVERGENCE_OPTION_SECOND_EXIT"
    with pytest.raises(ValueError, match="TRACK5_CLOSE_REQUIRES_AUTHORITATIVE_OPEN_LOT_RESOLVER"):
        strategy.build_execution_plan("s5-existing-position", proposal=proposal)


@pytest.mark.parametrize(
    ("state_changes", "price", "expected_reason"),
    [
        ({}, Decimal("111"), "OPTION_STOP_REQUIRES_HEDGE_CLOSE"),
        ({"open_ticks": 29}, Decimal("100"), "TIMEOUT_REQUIRES_HEDGE_CLOSE"),
        ({"trailing_active": True, "peak_pnl": Decimal("2")}, Decimal("100"), "TRAILING_EXIT_REQUIRES_HEDGE_CLOSE"),
    ],
)
def test_terminal_exit_triggers_route_to_grouped_close_with_trigger_quantity_only(state_changes, price, expected_reason):
    strategy, strategy.state = _active_legacy_strategy(**state_changes)
    signals = strategy.evaluate_mean_reversion(price)
    assert len(signals) == 1
    assert expected_reason in signals[0].reason
    proposal = signals[0].execution_proposal
    assert proposal.asset_type == "FUTURES"
    assert proposal.tag_id == "GAP_DIVERGENCE_TERMINAL_EXIT"
    assert proposal.proposed_quantity == strategy.EXIT_PROPOSAL_QUANTITY == 1
    assert strategy.state.futures_close_requested is True


def test_gap_fill_remains_futures_only_non_terminal_exit():
    strategy, strategy.state = _active_legacy_strategy()
    signals = strategy.evaluate_mean_reversion(Decimal("99"))
    assert len(signals) == 1
    proposal = signals[0].execution_proposal
    assert proposal.asset_type == "FUTURES"
    assert proposal.tag_id == "GAP_DIVERGENCE_FUTURES_FIRST_EXIT"
    assert proposal.proposed_quantity == strategy.EXIT_PROPOSAL_QUANTITY == 1


def test_strategy_builder_fails_closed_for_futures_close_without_authoritative_lot_resolver():
    strategy, strategy.state = _active_legacy_strategy(futures_close_requested=True)
    proposal = StrategyExecutionProposal(
        proposed_quantity=1,
        asset_type="FUTURES",
        side="BUY",
        track_id="track5_gap_divergence",
        tag_id="GAP_DIVERGENCE_FUTURES_FIRST_EXIT",
    )
    with pytest.raises(ValueError, match="TRACK5_CLOSE_REQUIRES_AUTHORITATIVE_OPEN_LOT_RESOLVER"):
        strategy.build_execution_plan("s5-existing-position", proposal=proposal)
