from core.strategy.contracts import StrategyContext
from core.strategy.track4_gamma_scalping import Track4GammaScalping


def test_track4_remains_disabled_without_explicit_enable_and_capital_gate() -> None:
    strategy = Track4GammaScalping()

    result = strategy.evaluate(StrategyContext(strategy_id=strategy.strategy_id))

    assert result == ()
    assert strategy.enabled is False
    assert strategy.capital_gate_min is None


def test_track4_enabled_flag_alone_does_not_bypass_missing_capital_gate() -> None:
    strategy = Track4GammaScalping(enabled=True)

    result = strategy.evaluate(StrategyContext(strategy_id=strategy.strategy_id))

    assert result == ()
    assert strategy.enabled is True
    assert strategy.capital_gate_min is None


def test_track4_capital_threshold_without_aggregate_risk_gate_stays_disabled() -> None:
    from decimal import Decimal
    from core.strategy.contracts import StrategyContext

    strategy = Track4GammaScalping(
        enabled=True, capital_gate_min=Decimal("1"), risk_limits_available=False
    )

    result = strategy.evaluate(StrategyContext(strategy_id=strategy.strategy_id))

    assert result == ()
