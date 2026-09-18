from datetime import datetime
from decimal import Decimal

from core.strategy.contracts import CommonStrategyInput, StrategyContext, StrategyInput
from core.strategy.track2_asymmetric_trap import Track2AsymmetricTrap, Track2MarketInputs
from core.strategy.track4_gamma_scalping import Track4GammaScalping, Track4MarketInput
from core.strategy.track7_volatility_skew_weekly_insurance import (
    Track7MarketInput,
    Track7VolatilitySkewWeeklyInsurance,
)


def track2_inputs(active_vol: float = 0.20, base_vol: float = 0.20) -> Track2MarketInputs:
    return Track2MarketInputs(
        bbw_window=(0.30, 0.20, 0.10), volume_window=(100.0, 100.0, 500.0),
        basis=Decimal("1.0"), put_iv=Decimal("0.15"), call_iv=Decimal("0.20"),
        poc_price=Decimal("495"),
        bid_qtys=tuple(Decimal("100") for _ in range(5)),
        ask_qtys=tuple(Decimal("1") for _ in range(5)),
        active_vol=active_vol, base_vol=base_vol,
    )


def track2_context() -> StrategyContext:
    as_of = datetime(2026, 9, 18, 10, 0)
    tick = type("Tick", (), {"instrument_id": "KOSPI200", "observed_at": as_of,
                              "price": Decimal("500"), "volume": Decimal("500")})()
    from core.domain.market_models import MarketState
    return StrategyContext(
        market_state=MarketState(as_of=as_of, ticks={"KOSPI200": tick}, quality={}),
        strategy_id="track2_asymmetric_trap",
        input=StrategyInput(common=CommonStrategyInput(as_of=as_of, current_price=Decimal("500")),
                            payload=track2_inputs()),
    )


def track4_data(**kwargs) -> Track4MarketInput:
    values = dict(
        observed_at=datetime(2026, 9, 18, 10, 0), current_price=Decimal("350"),
        active_vol=Decimal("1"), base_vol=Decimal("1"), time_str="10:00:00",
        current_delta=Decimal("0"), current_gamma=Decimal("0"), current_pnl=Decimal("0"),
        current_equity=Decimal("1000000"), price_history=(Decimal("350"), Decimal("351")),
    )
    values.update(kwargs)
    return Track4MarketInput(**values)


def track7_data(**kwargs) -> Track7MarketInput:
    values = dict(
        strategy_id="track7_volatility_skew_weekly_insurance", current_price=Decimal("350"),
        budget=Decimal("350000"), date_str="2026-09-18", is_new_week_start=True,
        active_vol=Decimal("1.0"),
    )
    values.update(kwargs)
    return Track7MarketInput(**values)


def test_track2_low_and_high_vol_trap_composition_is_preserved():
    strategy = Track2AsymmetricTrap()
    low = strategy.build_execution_plan("G1", Decimal("500"), 0.80, 1.0)
    high = strategy.build_execution_plan("G2", Decimal("500"), 1.0, 1.0)
    assert [(x.option_type, x.strike, x.side) for x in low.legs] == [
        ("PUT", Decimal("490.0"), "SELL"), ("CALL", Decimal("510.0"), "SELL"),
        ("PUT", Decimal("495.0"), "BUY"), ("CALL", Decimal("505.0"), "BUY")]
    assert [(x.option_type, x.strike, x.side) for x in high.legs] == [
        ("PUT", Decimal("492.5"), "SELL"), ("CALL", Decimal("507.5"), "SELL"),
        ("PUT", Decimal("497.5"), "BUY"), ("CALL", Decimal("502.5"), "BUY")]


def test_track2_trigger_filters_and_runtime_signal_keep_proposal():
    strategy = Track2AsymmetricTrap()
    assert strategy.check_market_trigger((0.3, 0.2, 0.1), (100, 100, 500))
    assert strategy.validate_whipsaw_filters(
        Decimal("500"), tuple(Decimal("100") for _ in range(5)),
        tuple(Decimal("1") for _ in range(5)), Decimal("1"), Decimal("0.15"),
        Decimal("0.20"), Decimal("495"))
    signal = strategy.evaluate(track2_context())[0]
    assert signal.reason == "ASYMMETRIC_TRAP_ENTRY"
    assert signal.execution_proposal is not None
    assert signal.execution_proposal.asset_type == "OPTION"


def test_track2_cutoff_and_cooldown_fail_closed():
    strategy = Track2AsymmetricTrap()
    context = track2_context()
    late = StrategyContext(market_state=context.market_state.__class__(
        as_of=datetime(2026, 9, 18, 15, 15), ticks=context.market_state.ticks, quality={}),
        strategy_id=context.strategy_id, input=context.input)
    assert strategy.evaluate(late) == ()
    strategy._last_loss_at = datetime(2026, 9, 18, 10, 0)
    assert strategy.evaluate(context) == ()


def test_track4_low_high_vol_and_cutoff_basecamp():
    strategy = Track4GammaScalping()
    low = strategy.evaluate_basecamp(track4_data(active_vol=Decimal("0.85")))
    assert "WIDE_BASECAMP" in low[0].reason
    strategy.reset()
    high = strategy.evaluate_basecamp(track4_data(active_vol=Decimal("1.30")))
    assert "ATM_BASECAMP" in high[0].reason
    strategy.reset()
    assert strategy.evaluate_basecamp(track4_data(active_vol=Decimal("0.85"), time_str="15:15:00")) == ()


def test_track4_deadband_theta_and_hedge_quantity():
    assert Track4GammaScalping.calculate_observed_tick_deadband(()) == Decimal("0")
    assert Track4GammaScalping.calculate_observed_tick_deadband((Decimal("350"),)) == Decimal("0.2")
    assert Track4GammaScalping.theta_guard(Decimal("10"), Decimal("10")) is False
    assert Track4GammaScalping.theta_guard(Decimal("10.01"), Decimal("10")) is True
    hedge = Track4GammaScalping().evaluate_delta_hedge(track4_data(current_delta=Decimal("0.41")))[0]
    assert hedge.execution_proposal is not None
    assert hedge.execution_proposal.proposed_quantity == 3
    assert hedge.execution_proposal.side == "SELL"


def test_track4_equity_unwind_and_trailing_reset():
    strategy = Track4GammaScalping(equity_threshold=Decimal("100"))
    strategy.state.active_hedge_qty = 3
    unwind = strategy.evaluate_delta_hedge(track4_data(current_delta=Decimal("1"), current_equity=Decimal("99")))
    assert unwind and "UNWIND_FUT_HEDGE" in unwind[0].reason
    strategy.state.scalp_high_pnl = Decimal("40000")
    close = strategy.evaluate_profit_trailing(track4_data(current_pnl=Decimal("30000"), premium_spent=Decimal("30000")))
    assert close and close[0].direction == "CLOSE"
    assert strategy.state.scalp_high_pnl == Decimal("0")
    assert strategy.state.active_hedge_qty == 0


def test_track7_weekly_insurance_and_skew_entry_fallback():
    strategy = Track7VolatilitySkewWeeklyInsurance()
    insurance = strategy.evaluate_insurance_buy(track7_data())
    assert insurance and insurance[0].direction == "BUY_LIMIT_WEEKLY_INSURANCE"
    strategy.reset()
    entry = strategy.evaluate_skew_arbitrage(track7_data(call_iv=Decimal("10"), put_iv=Decimal("13")))
    assert entry and entry[0].direction == "ENTER_SKEW_ARB_LIMIT"
    fallback = strategy.evaluate_skew_arbitrage(track7_data(call_iv=Decimal("10"), put_iv=Decimal("13"), skew_limit_timeout=True))
    assert fallback and fallback[0].direction == "ENTER_SKEW_ARB_FALLBACK_MARKET"


def test_track7_skew_exit_stop_and_expiry_cutoff():
    strategy = Track7VolatilitySkewWeeklyInsurance()
    strategy.evaluate_skew_arbitrage(track7_data(call_iv=Decimal("10"), put_iv=Decimal("13")))
    assert strategy.evaluate_skew_arbitrage(track7_data(call_iv=Decimal("10"), put_iv=Decimal("19")))[0].direction == "CLOSE_SKEW_ARB_STOP_LOSS"
    strategy.evaluate_skew_arbitrage(track7_data(call_iv=Decimal("10"), put_iv=Decimal("13")))
    assert strategy.evaluate_skew_arbitrage(track7_data(call_iv=Decimal("10"), put_iv=Decimal("10.4")))[0].direction == "CLOSE_SKEW_ARB_LIMIT"
    strategy.reset()
    strategy.evaluate_insurance_buy(track7_data())
    assert strategy.evaluate_expiry_cutoff(track7_data(time_str="15:05:00", is_expiry_day=True))[0].direction == "CLOSE_WEEKLY_INSURANCE_LIMIT"
    strategy.reset()
    strategy.evaluate_insurance_buy(track7_data())
    assert strategy.evaluate_expiry_cutoff(track7_data(time_str="15:15:00", is_expiry_day=True))[0].direction == "CLOSE_WEEKLY_INSURANCE_FALLBACK_MARKET"


def test_track7_missing_optional_ma_does_not_fabricate_take_profit():
    strategy = Track7VolatilitySkewWeeklyInsurance()
    strategy.evaluate_insurance_buy(track7_data())
    assert strategy.evaluate_preemptive_take_profit(track7_data()) == ()
    assert strategy.evaluate(track7_data(strategy_id="other")) == ()
