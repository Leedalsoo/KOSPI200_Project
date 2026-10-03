from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from contracts.analytics import AnalyticsStatus
from core.strategy.contracts import SignalKind
from core.strategy.track6_daily_tail_insurance import Track6DailyTailInsurance, Track6State
from core.strategy.contracts import StrategyContext


def snapshot(time_str, values):
    metrics = {k: SimpleNamespace(status=AnalyticsStatus.AVAILABLE, value=v) for k, v in values.items()}
    return SimpleNamespace(
        as_of=datetime.fromisoformat(f"2026-10-01T{time_str}"),
        get=lambda key: metrics.get(key),
    )


def active_strategy():
    strategy = Track6DailyTailInsurance()
    strategy.state = Track6State(
        is_active=True,
        bought_date="2026-10-01",
        long_put_strike=Decimal("100"),
        long_call_strike=Decimal("100"),
        high_watermark_intrinsic=Decimal("20"),
        trailing_stop_active=True,
    )
    return strategy


def test_trailing_close_has_authoritative_execution_proposal():
    strategy = active_strategy()
    analytics = snapshot("10:00:00", {
        "price.last": Decimal("99"),
        "volatility.active": Decimal("1"),
        "portfolio.premium_spent": Decimal("10"),
    })
    signals = strategy.evaluate_take_profit(StrategyContext(strategy_id=strategy.strategy_id, analytics=analytics))
    assert len(signals) == 1
    signal = signals[0]
    assert signal.direction == "CLOSE"
    assert signal.execution_proposal is not None
    assert signal.execution_proposal.side == "SELL"
    assert signal.execution_proposal.option_type == "PUT"
    assert signal.execution_proposal.strike == Decimal("100")


def test_trailing_update_is_non_execution_event():
    strategy = active_strategy()
    strategy.state = Track6State(is_active=True, long_put_strike=Decimal("100"), long_call_strike=Decimal("100"))
    analytics = snapshot("10:00:00", {
        "price.last": Decimal("120"),
        "volatility.active": Decimal("1"),
        "portfolio.premium_spent": Decimal("10"),
    })
    signals = strategy.evaluate_take_profit(StrategyContext(strategy_id=strategy.strategy_id, analytics=analytics))
    assert len(signals) == 1
    signal = signals[0]
    assert signal.direction == "UPDATE_TRAILING"
    assert signal.kind is SignalKind.NON_EXECUTION
    assert signal.execution_proposal is None
    assert signal.non_execution_event is not None


def test_daily_close_limit_has_execution_proposal():
    strategy = active_strategy()
    analytics = snapshot("15:05:00", {})
    signals = strategy.evaluate_expiry_cutoff(StrategyContext(strategy_id=strategy.strategy_id, analytics=analytics))
    assert len(signals) == 1
    assert signals[0].direction == "CLOSE_LIMIT"
    assert signals[0].execution_proposal is not None
    assert signals[0].execution_proposal.tag_id == "DAILY_TAIL_INSURANCE_LIMIT_CLOSE"


def test_daily_close_fallback_has_execution_proposal():
    strategy = active_strategy()
    analytics = snapshot("15:15:00", {})
    signals = strategy.evaluate_expiry_cutoff(StrategyContext(strategy_id=strategy.strategy_id, analytics=analytics))
    assert len(signals) == 1
    assert signals[0].direction == "CLOSE_FALLBACK"
    assert signals[0].execution_proposal is not None
    assert signals[0].execution_proposal.tag_id == "DAILY_TAIL_INSURANCE_FALLBACK_CLOSE"
