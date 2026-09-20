from datetime import datetime
from decimal import Decimal
import inspect

from contracts.analytics import AnalyticsProvenance, AnalyticsRequest, MarketSnapshot
from core.analytics.engine import AnalyticsEngine
from core.analytics.track7 import build_track7_evaluators
from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.track7_volatility_skew_weekly_insurance import Track7VolatilitySkewWeeklyInsurance

STRATEGY_ID = "track7_volatility_skew_weekly_insurance"


def context(**observations):
    as_of = observations.pop("as_of", datetime(2026, 9, 18, 10, 0))
    keys = tuple(
        (key, (dep,)) for key, dep in (
            ("price.last", "current_price"), ("options.call_iv", "call_iv"),
            ("options.put_iv", "put_iv"), ("options.skew", "call_iv"),
            ("trend.ma_1m", "ma_1m"), ("trend.ma_3m", "ma_3m"),
            ("trend.ma_5m", "ma_5m"), ("trend.ma_10m", "ma_10m"),
            ("levels.support", "support"), ("levels.resistance", "resistance"),
            ("calendar.is_new_week_start", "is_new_week_start"),
            ("calendar.is_expiry_day", "is_expiry_day"),
            ("calendar.is_week_end", "is_week_end"),
            ("execution.order_timeout", "order_timeout"),
        )
    )
    fixed = dict(
        current_price=Decimal("350"), call_iv=Decimal("10"), put_iv=Decimal("10"),
        ma_1m=Decimal("350"), ma_3m=Decimal("350"), ma_5m=Decimal("350"), ma_10m=Decimal("350"),
        support=Decimal("348.35"), resistance=Decimal("356.65"),
        is_new_week_start=False, is_expiry_day=False, is_week_end=False, order_timeout=False,
    )
    fixed.update(observations)
    snapshot = MarketSnapshot("track7-test", as_of, AnalyticsProvenance("test"), None, fixed)
    requests = tuple(AnalyticsRequest(k, "tick", 1, deps, 1.0, "authoritative", "1") for k, deps in keys)
    analytics = AnalyticsEngine(build_track7_evaluators()).evaluate(snapshot, requests)
    return StrategyContext(strategy_id=STRATEGY_ID, input=StrategyInput(), analytics=analytics)


def test_new_week_buy_fails_closed_without_authoritative_contract_selection():
    s = Track7VolatilitySkewWeeklyInsurance()
    assert s.evaluate(context(is_new_week_start=True)) == ()


def test_skew_entry_and_fallback():
    s = Track7VolatilitySkewWeeklyInsurance()
    signals = s.evaluate(context(call_iv=Decimal("10"), put_iv=Decimal("13")))
    assert signals[0].direction == "ENTER_SKEW_ARB_LIMIT"
    signals = s.evaluate(context(call_iv=Decimal("10"), put_iv=Decimal("13"), order_timeout=True))
    assert any(x.direction == "ENTER_SKEW_ARB_FALLBACK_MARKET" for x in signals)


def test_skew_stop_and_normal_exit():
    s = Track7VolatilitySkewWeeklyInsurance()
    s.evaluate(context(call_iv=Decimal("10"), put_iv=Decimal("13")))
    assert s.evaluate(context(call_iv=Decimal("10"), put_iv=Decimal("19")))[0].direction == "CLOSE_SKEW_ARB_STOP_LOSS"
    s.evaluate(context(call_iv=Decimal("10"), put_iv=Decimal("13")))
    assert s.evaluate(context(call_iv=Decimal("10"), put_iv=Decimal("10.4")))[0].direction == "CLOSE_SKEW_ARB_LIMIT"


def test_preemptive_take_profit_requires_real_ma_inputs():
    s = Track7VolatilitySkewWeeklyInsurance()
    s.state = s.state.__class__(insurance_active=True)
    assert s.evaluate_preemptive_take_profit(context(ma_1m=None)) == ()
    signals = s.evaluate_preemptive_take_profit(context(ma_1m=Decimal("354"), ma_3m=Decimal("353"), ma_5m=Decimal("352"), ma_10m=Decimal("351")))
    assert signals and signals[0].direction == "PREEMPTIVE_LIMIT_TAKE_PROFIT"


def test_expiry_cutoff_limit_then_fallback():
    s = Track7VolatilitySkewWeeklyInsurance()
    s.state = s.state.__class__(insurance_active=True)
    limit = context(is_expiry_day=True, as_of=datetime(2026, 9, 18, 15, 5))
    assert s.evaluate_expiry_cutoff(limit)[0].direction == "CLOSE_WEEKLY_INSURANCE_LIMIT"
    fallback = context(is_expiry_day=True, as_of=datetime(2026, 9, 18, 15, 15))
    s.state = s.state.__class__(insurance_active=True)
    assert s.evaluate_expiry_cutoff(fallback)[0].direction == "CLOSE_WEEKLY_INSURANCE_FALLBACK_MARKET"


def test_strategy_id_mismatch_is_noop():
    s = Track7VolatilitySkewWeeklyInsurance()
    bad = context()
    bad = StrategyContext(strategy_id="other_strategy", input=bad.input, analytics=bad.analytics)
    assert s.evaluate(bad) == ()


def test_strategy_has_no_legacy_order_dependency():
    from core.strategy import track7_volatility_skew_weekly_insurance
    source = inspect.getsource(track7_volatility_skew_weekly_insurance)
    assert "OrderRequest" not in source
    assert "Broker" not in source
    assert "MULTIPLIER" not in source
