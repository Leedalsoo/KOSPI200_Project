from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from core.strategy.track4_gamma_scalping import Track4GammaScalping, Track4MarketInput


def _market_input() -> Track4MarketInput:
    return Track4MarketInput(
        observed_at=datetime(2026, 11, 25, 10, 0),
        current_price=Decimal("880"),
        active_vol=Decimal("20"),
        base_vol=Decimal("15"),
        time_str="10:00:00",
        current_delta=Decimal("1000000"),
        current_gamma=Decimal("1"),
        current_pnl=Decimal("0"),
        current_equity=Decimal("1000000"),
        price_history=(Decimal("879"), Decimal("880")),
    )


def test_track4_strategy_state_records_hedge_target_before_any_fill() -> None:
    """Characterize target-vs-actual state; this is not a Production approval."""
    strategy = Track4GammaScalping(
        enabled=True,
        capital_gate_min=Decimal("1"),
        risk_limits_available=True,
    )

    signals = strategy.evaluate_delta_hedge(
        _market_input(),
        delta=Decimal("1000000"),
        deadband=Decimal("0"),
        equity=Decimal("1000000"),
        max_hedge_qty=2,
    )

    assert len(signals) == 1
    proposal = signals[0].execution_proposal
    assert proposal is not None
    assert proposal.tag_id == "GAMMA_REBALANCE"
    assert proposal.side == "SELL"
    assert proposal.proposed_quantity == 2

    # The strategy records the target as active before an execution result exists.
    assert strategy.state.active_hedge_qty == -2

    # A synthetic partial/pending result is not consumed by the entry callback.
    strategy.on_execution_result(
        "GAMMA_REBALANCE",
        SimpleNamespace(
            group_complete=False,
            position_flat=False,
            filled_quantity=1,
            remaining_quantity=1,
            pending_legs=1,
        ),
    )
    assert strategy.state.active_hedge_qty == -2

    # A synthetic rejected/no-fill result also leaves the target recorded as active.
    strategy.on_execution_result(
        "GAMMA_REBALANCE",
        SimpleNamespace(
            group_complete=False,
            position_flat=True,
            filled_quantity=0,
            remaining_quantity=2,
            pending_legs=0,
        ),
    )
    assert strategy.state.active_hedge_qty == -2
