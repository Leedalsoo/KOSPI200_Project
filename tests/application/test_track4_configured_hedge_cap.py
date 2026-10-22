from datetime import datetime
from decimal import Decimal

from core.strategy.track4_gamma_scalping import Track4GammaScalping, Track4MarketInput


def _input() -> Track4MarketInput:
    return Track4MarketInput(
        observed_at=datetime(2026, 10, 21, 10, 0),
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


def test_track4_delta_hedge_blocks_when_configured_max_hedge_qty_is_missing():
    strategy = Track4GammaScalping(enabled=True, capital_gate_min=Decimal("1"), risk_limits_available=True)

    result = strategy.evaluate_delta_hedge(
        _input(),
        delta=Decimal("1000000"),
        deadband=Decimal("0"),
        equity=Decimal("1000000"),
        max_hedge_qty=None,
    )

    assert result == ()


def test_track4_delta_hedge_respects_configured_max_hedge_qty():
    strategy = Track4GammaScalping(enabled=True, capital_gate_min=Decimal("1"), risk_limits_available=True)

    result = strategy.evaluate_delta_hedge(
        _input(),
        delta=Decimal("1000000"),
        deadband=Decimal("0"),
        equity=Decimal("1000000"),
        max_hedge_qty=2,
    )

    assert len(result) == 1
    assert result[0].execution_proposal.proposed_quantity == 2
