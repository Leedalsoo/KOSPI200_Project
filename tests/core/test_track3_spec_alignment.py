from types import SimpleNamespace

from core.strategy.track3_statistical_arbitrage import (
    Track3MarketInput,
    Track3StatisticalArbitrage,
)


def test_track3_exit_pending_does_not_read_regime_before_assignment() -> None:
    strategy = Track3StatisticalArbitrage()
    strategy._exit_pending = True
    analytics = {
        "spread.z_score": SimpleNamespace(value=0.4),
        "spread.std": SimpleNamespace(value=1.0),
        "volatility.ratio": SimpleNamespace(value=1.0),
        "microstructure.spread": SimpleNamespace(value=0.2),
        "price.change_rate": SimpleNamespace(value=0.0),
        "market.gap_pct": SimpleNamespace(value=0.0),
        "market.current_regime": SimpleNamespace(value="NORMAL"),
    }

    result = strategy.evaluate_input(
        Track3MarketInput(date_str="20261021"), analytics
    )

    assert result.status == "EXIT_PENDING"
    assert result.regime == "NORMAL"
    assert result.z_score == 0.4
    assert result.signals == ()


def test_track3_entry_is_blocked_until_enabled_and_capital_gate_are_set() -> None:
    strategy = Track3StatisticalArbitrage()
    analytics = {
        "spread.z_score": SimpleNamespace(value=4.0),
        "spread.std": SimpleNamespace(value=10.0),
        "volatility.ratio": SimpleNamespace(value=1.0),
        "microstructure.spread": SimpleNamespace(value=0.1),
        "price.change_rate": SimpleNamespace(value=0.0),
        "market.gap_pct": SimpleNamespace(value=0.0),
        "market.current_regime": SimpleNamespace(value="NORMAL"),
    }

    result = strategy.evaluate_input(
        Track3MarketInput(date_str="20261021"), analytics
    )

    assert result.status == "BLOCKED"
    assert result.signals == ()
    assert strategy.active_position is None


def test_track3_remains_blocked_even_with_capital_flag_without_authoritative_spread_identity() -> None:
    strategy = Track3StatisticalArbitrage(
        enabled=True, capital_gate_min=1.0, risk_limits_available=True
    )
    analytics = {
        "spread.z_score": SimpleNamespace(value=4.0),
        "spread.std": SimpleNamespace(value=10.0),
        "volatility.ratio": SimpleNamespace(value=1.0),
        "microstructure.spread": SimpleNamespace(value=0.1),
        "price.change_rate": SimpleNamespace(value=0.0),
        "market.gap_pct": SimpleNamespace(value=0.0),
        "market.current_regime": SimpleNamespace(value="NORMAL"),
    }

    result = strategy.evaluate_input(
        Track3MarketInput(date_str="20261021"), analytics
    )

    assert result.status == "BLOCKED"
    assert result.signals == ()
    assert strategy.active_position is None
