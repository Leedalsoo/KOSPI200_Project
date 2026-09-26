from datetime import datetime
from decimal import Decimal

from contracts.analytics import AnalyticsProvenance, AnalyticsRequest, MarketSnapshot
from core.analytics.engine import AnalyticsEngine
from core.analytics.track2 import build_track2_evaluators
from application.composition.track4_analytics_provider import build_track4_analytics_snapshot
from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.track2_asymmetric_trap import Track2AsymmetricTrap
from core.strategy.track4_gamma_scalping import Track4GammaScalping, Track4MarketInput
from application.composition.track7_analytics_provider import build_track7_analytics_snapshot
from core.strategy.track7_volatility_skew_weekly_insurance import Track7VolatilitySkewWeeklyInsurance


def track2_context() -> StrategyContext:
    as_of = datetime(2026, 9, 18, 10, 0)
    tick = type("Tick", (), {"instrument_id": "KOSPI200", "observed_at": as_of, "price": Decimal("500"), "volume": Decimal("500")})()
    from core.domain.market_models import MarketState
    observations = {"bbw_window": (0.30, 0.20, 0.10), "volume_window": (100.0, 100.0, 500.0), "basis": Decimal("1.0"), "put_iv": Decimal("15.0"), "call_iv": Decimal("20.0"), "poc_price": Decimal("495"), "bid_qtys": (Decimal("100"),) * 5, "ask_qtys": (Decimal("1"),) * 5, "active_vol": Decimal("0.20"), "base_vol": Decimal("0.20")}
    market = MarketSnapshot("REGRESSION", as_of, AnalyticsProvenance("regression"), None, observations)
    keys = (("volatility.bbw", ("bbw_window",)), ("volume.z_score", ("volume_window",)), ("microstructure.obi", ("bid_qtys", "ask_qtys")), ("futures.basis", ("basis",)), ("options.put_iv", ("put_iv",)), ("options.call_iv", ("call_iv",)), ("volume_profile.poc", ("poc_price",)), ("volatility.active", ("active_vol",)), ("volatility.base", ("base_vol",)))
    requests = tuple(AnalyticsRequest(k, "tick", 20, d, 1.0, "authoritative", "1") for k, d in keys)
    analytics = AnalyticsEngine(build_track2_evaluators()).evaluate(market, requests)
    return StrategyContext(market_state=MarketState(as_of=as_of, ticks={"KOSPI200": tick}, quality={}), strategy_id="track2_asymmetric_trap", analytics=analytics)


def track4_data(**kwargs) -> Track4MarketInput:
    values = dict(observed_at=datetime(2026, 9, 18, 10, 0), current_price=Decimal("350"), active_vol=Decimal("1"), base_vol=Decimal("1"), time_str="10:00:00", current_delta=Decimal("0"), current_gamma=Decimal("0"), current_pnl=Decimal("0"), current_equity=Decimal("1000000"), price_history=(Decimal("350"), Decimal("351")), current_theta=Decimal("-0.07"))
    values.update(kwargs)
    return Track4MarketInput(**values)


def _track4_context(data):
    return StrategyContext(strategy_id="track4_gamma_scalping", input=StrategyInput(payload=data), analytics=build_track4_analytics_snapshot(data, run_id="regression", as_of=data.observed_at))


def test_track2_low_and_high_vol_trap_composition_is_preserved():
    strategy = Track2AsymmetricTrap()
    low = strategy.build_execution_plan("G1", Decimal("500"), 0.80, 1.0)
    high = strategy.build_execution_plan("G2", Decimal("500"), 1.0, 1.0)
    assert [(x.option_type, x.strike, x.side) for x in low.legs] == [("PUT", Decimal("490.0"), "SELL"), ("CALL", Decimal("510.0"), "SELL"), ("PUT", Decimal("495.0"), "BUY"), ("CALL", Decimal("505.0"), "BUY")]
    assert [(x.option_type, x.strike, x.side) for x in high.legs] == [("PUT", Decimal("492.5"), "SELL"), ("CALL", Decimal("507.5"), "SELL"), ("PUT", Decimal("497.5"), "BUY"), ("CALL", Decimal("502.5"), "BUY")]


def test_track2_trigger_filters_and_runtime_signal_keep_proposal():
    signal = Track2AsymmetricTrap().evaluate(track2_context())[0]
    assert signal.reason == "ASYMMETRIC_TRAP_ENTRY"
    assert signal.execution_proposal is not None
    assert signal.execution_proposal.asset_type == "OPTION"


def test_track2_cutoff_and_cooldown_fail_closed():
    strategy = Track2AsymmetricTrap()
    context = track2_context()
    late = StrategyContext(market_state=context.market_state.__class__(as_of=datetime(2026, 9, 18, 15, 15), ticks=context.market_state.ticks, quality={}), strategy_id=context.strategy_id, analytics=context.analytics)
    assert strategy.evaluate(late) == ()
    strategy._last_loss_at = datetime(2026, 9, 18, 10, 0)
    assert strategy.evaluate(context) == ()


def test_track4_low_high_vol_and_cutoff_basecamp():
    strategy = Track4GammaScalping()
    low = strategy.evaluate(_track4_context(track4_data(active_vol=Decimal("0.85"))))
    assert "WIDE_BASECAMP" in low[0].reason
    strategy.reset()
    high = strategy.evaluate(_track4_context(track4_data(active_vol=Decimal("1.30"))))
    assert "ATM_BASECAMP" in high[0].reason
    strategy.reset()
    assert strategy.evaluate(_track4_context(track4_data(active_vol=Decimal("0.85"), time_str="15:15:00"))) == ()


def test_track4_deadband_theta_and_hedge_quantity():
    data = track4_data(current_delta=Decimal("0.41"))
    analytics = build_track4_analytics_snapshot(data, run_id="regression", as_of=data.observed_at)
    assert analytics.get("options.theta").value == Decimal("-0.07")
    assert analytics.get("price.tick_deadband").value == Decimal("0.2")
    hedge = Track4GammaScalping().evaluate(StrategyContext(strategy_id="track4_gamma_scalping", input=StrategyInput(payload=data), analytics=analytics))[0]
    assert hedge.execution_proposal is not None
    assert hedge.execution_proposal.proposed_quantity == 3
    assert hedge.execution_proposal.side == "SELL"


def test_track4_equity_unwind_and_trailing_reset():
    strategy = Track4GammaScalping(equity_threshold=Decimal("100"))
    strategy.state.active_hedge_qty = 3
    unwind_data = track4_data(current_delta=Decimal("1"), current_equity=Decimal("99"))
    unwind = strategy.evaluate(_track4_context(unwind_data))
    assert unwind and "UNWIND_FUT_HEDGE" in unwind[0].reason
    strategy.state.scalp_high_pnl = Decimal("40000")
    close_data = track4_data(current_pnl=Decimal("30000"), premium_spent=Decimal("30000"))
    close = strategy.evaluate_profit_trailing(close_data, current_pnl=Decimal("30000"), premium_spent=Decimal("30000"))
    assert close and close[0].direction == "CLOSE"
    assert strategy.state.scalp_high_pnl == Decimal("0")
    assert strategy.state.active_hedge_qty == 0


def track7_context(**observations) -> StrategyContext:
    as_of = observations.pop("as_of", datetime(2026, 9, 18, 10, 0))
    values = dict(
        price=Decimal("350"), option_iv=Decimal("10"), put_iv=Decimal("10"),
        ma_1m=Decimal("350"), ma_3m=Decimal("350"), ma_5m=Decimal("350"), ma_10m=Decimal("350"),
        support=Decimal("348.35"), resistance=Decimal("356.65"),
        is_new_week_start=False, is_expiry_day=False, is_week_end=False, order_timeout=False,
    )
    values.update(observations)
    data = type("RuntimeData", (), values)()
    return StrategyContext(strategy_id="track7_volatility_skew_weekly_insurance", input=StrategyInput(),
                           analytics=build_track7_analytics_snapshot(data, run_id="regression", as_of=as_of))


def test_track7_weekly_insurance_fails_closed_and_skew_uses_common_analytics():
    strategy = Track7VolatilitySkewWeeklyInsurance()
    assert strategy.evaluate(track7_context(is_new_week_start=True)) == ()
    entry = strategy.evaluate(track7_context(option_iv=Decimal("10"), put_iv=Decimal("13")))
    assert entry and entry[0].direction == "ENTER_SKEW_ARB_LIMIT"
    fallback = strategy.evaluate(track7_context(option_iv=Decimal("10"), put_iv=Decimal("13"), order_timeout=True))
    assert fallback and fallback[0].direction == "ENTER_SKEW_ARB_FALLBACK_MARKET"


def test_track7_skew_exit_stop_and_expiry_cutoff():
    strategy = Track7VolatilitySkewWeeklyInsurance()
    strategy.evaluate(track7_context(option_iv=Decimal("10"), put_iv=Decimal("13")))
    assert strategy.evaluate(track7_context(option_iv=Decimal("10"), put_iv=Decimal("19")))[0].direction == "CLOSE_SKEW_ARB_STOP_LOSS"
    strategy.evaluate(track7_context(option_iv=Decimal("10"), put_iv=Decimal("13")))
    assert strategy.evaluate(track7_context(option_iv=Decimal("10"), put_iv=Decimal("10.4")))[0].direction == "CLOSE_SKEW_ARB_LIMIT"
    strategy.state = strategy.state.__class__(insurance_active=True)
    assert strategy.evaluate_expiry_cutoff(track7_context(is_expiry_day=True, as_of=datetime(2026, 9, 18, 15, 5)))[0].direction == "CLOSE_WEEKLY_INSURANCE_LIMIT"
    strategy.state = strategy.state.__class__(insurance_active=True)
    assert strategy.evaluate_expiry_cutoff(track7_context(is_expiry_day=True, as_of=datetime(2026, 9, 18, 15, 15)))[0].direction == "CLOSE_WEEKLY_INSURANCE_FALLBACK_MARKET"


def test_track7_strategy_is_fail_closed_without_contract_identity():
    strategy = Track7VolatilitySkewWeeklyInsurance()
    assert strategy.evaluate(track7_context(is_new_week_start=True)) == ()
