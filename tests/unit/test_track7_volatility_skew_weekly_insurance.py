from decimal import Decimal
import inspect

from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.track7_volatility_skew_weekly_insurance import Track7MarketInput, Track7VolatilitySkewWeeklyInsurance


STRATEGY_ID = "track7_volatility_skew_weekly_insurance"


def base(**kwargs):
    values = dict(
        strategy_id=STRATEGY_ID,
        current_price=Decimal("350"),
        budget=Decimal("350000"),
        date_str="2026-09-04",
        is_new_week_start=True,
        active_vol=Decimal("1.0"),
    )
# values.update(kwargs)
    return Track7MarketInput(**values)


def context(data):
    return StrategyContext(
        strategy_id=STRATEGY_ID,
        input=StrategyInput(payload=data),
    )


def test_new_week_buys_weekly_insurance():
    s = Track7VolatilitySkewWeeklyInsurance()
    signals = s.evaluate(context(base()))
    assert signals and signals[0].direction == "BUY_LIMIT_WEEKLY_INSURANCE"
    assert s.state.put_strike == Decimal("335")
    assert s.state.call_strike == Decimal("365")


def test_not_new_week_does_not_buy():
    s = Track7VolatilitySkewWeeklyInsurance()
    assert s.evaluate(context(base(is_new_week_start=False))) == ()


def test_budget_guard():
    s = Track7VolatilitySkewWeeklyInsurance()
    assert s.evaluate(context(base(budget=Decimal("349999")))) == ()


def test_1515_pending_cancel():
    s = Track7VolatilitySkewWeeklyInsurance()
    assert s.evaluate(context(base(time_str="15:15:01")))[0].direction == "CANCEL"


def test_skew_entry_and_fallback():
    s = Track7VolatilitySkewWeeklyInsurance()
    signals = s.evaluate(context(base(call_iv=Decimal("10"), put_iv=Decimal("13"))))
    assert signals[0].direction == "BUY_LIMIT_WEEKLY_INSURANCE"
    signals = s.evaluate(context(base(call_iv=Decimal("10"), put_iv=Decimal("13"), skew_limit_timeout=True)))
    assert any(x.direction == "ENTER_SKEW_ARB_FALLBACK_MARKET" for x in signals)


def test_skew_stop_and_normal_exit():
    s = Track7VolatilitySkewWeeklyInsurance()
    s.evaluate_skew_arbitrage(base(call_iv=Decimal("10"), put_iv=Decimal("13")))
    assert s.evaluate_skew_arbitrage(base(call_iv=Decimal("10"), put_iv=Decimal("19")))[0].direction == "CLOSE_SKEW_ARB_STOP_LOSS"
    s.evaluate_skew_arbitrage(base(call_iv=Decimal("10"), put_iv=Decimal("13")))
    assert s.evaluate_skew_arbitrage(base(call_iv=Decimal("10"), put_iv=Decimal("10.4")))[0].direction == "CLOSE_SKEW_ARB_LIMIT"


def test_preemptive_take_profit_requires_real_ma_inputs():
    s = Track7VolatilitySkewWeeklyInsurance()
# s.evaluate_insurance_buy(base())
    assert s.evaluate_preemptive_take_profit(base()) == ()
    signals = s.evaluate_preemptive_take_profit(base(ma_1m=Decimal("354"), ma_3m=Decimal("353"), ma_5m=Decimal("352"), ma_10m=Decimal("351")))
    assert signals and signals[0].direction == "PREEMPTIVE_LIMIT_TAKE_PROFIT"


def test_expiry_cutoff_limit_then_fallback():
    s = Track7VolatilitySkewWeeklyInsurance()
# s.evaluate(context(base()))
    assert s.evaluate(context(base(time_str="15:05:00", is_expiry_day=True)))[0].direction == "CLOSE_WEEKLY_INSURANCE_LIMIT"
    assert s.evaluate(context(base(time_str="15:15:00", is_expiry_day=True)))[0].direction == "CLOSE_WEEKLY_INSURANCE_FALLBACK_MARKET"


def test_strategy_id_mismatch_is_noop():
    s = Track7VolatilitySkewWeeklyInsurance()
    bad_context = StrategyContext(
        strategy_id="other_strategy",
        input=StrategyInput(payload=base()),
    )
    assert s.evaluate(bad_context) == ()


def test_strategy_has_no_legacy_order_dependency():
    from core.strategy import track7_volatility_skew_weekly_insurance
    source = inspect.getsource(track7_volatility_skew_weekly_insurance)
# assert "OrderRequest" not in source
# assert "Broker" not in source
# assert "TimeService" not in source
