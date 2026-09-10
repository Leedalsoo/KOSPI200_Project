from decimal import Decimal
import inspect

from core.strategy.contracts import StrategyContext, StrategyInput
from core.strategy.track8_macro_regime_monthly_strangle import (
    Track8MacroRegimeMonthlyStrangle,
    Track8MarketInput,
)


STRATEGY_ID = "track8_macro_regime_monthly_strangle"


def base(**kwargs):
    values = dict(
        strategy_id=STRATEGY_ID,
        dte=Decimal("20"),
        budget=Decimal("2000000"),
        current_price=Decimal("350"),
        current_regime="NORMAL",
        date_str="2026-09-04",
    )
    values.update(kwargs)
    return Track8MarketInput(**values)


def context(data):
    return StrategyContext(
        strategy_id=STRATEGY_ID,
        input=StrategyInput(payload=data),
    )


def test_monthly_entry_via_standard_context():
    s = Track8MacroRegimeMonthlyStrangle()
    signals = s.evaluate(context(base()))
    assert any(x.direction == "BUY_LIMIT_TRANCHE" for x in signals)
    assert s.state.call_strike == Decimal("365")
    assert s.state.put_strike == Decimal("335")


def test_dte_and_budget_guards():
    s = Track8MacroRegimeMonthlyStrangle()
    assert s.evaluate(context(base(dte=Decimal("14.9")))) == ()
    assert s.evaluate(context(base(budget=Decimal("199999")))) == ()


def test_high_vol_asymmetric_qty():
    s = Track8MacroRegimeMonthlyStrangle()
    s.evaluate(context(base(current_regime="HIGH_VOL")))
    assert s.state.qty_put == s.state.qty_call * 2


def test_macro_regime_hedge_signal():
    s = Track8MacroRegimeMonthlyStrangle()
    signals = s.evaluate(context(base(current_regime="CRASH")))
    assert any(x.direction == "MACRO_HEDGE_SCALE_UP" for x in signals)


def test_profit_rebuild_and_risk_guard():
    s = Track8MacroRegimeMonthlyStrangle()
    s.evaluate(context(base()))
    signals = s.evaluate_profit_rebuild(
        base(current_price=Decimal("360"), current_pnl=Decimal("400000"))
    )
    assert len(signals) == 2
    assert signals[0].direction == "DYNAMIC_PROFIT_TAKE"
    assert signals[1].direction == "DYNAMIC_REBUILD_FENCE"

    assert s.evaluate_profit_rebuild(
        base(current_pnl=Decimal("400000"), risk_guard_active=True)
    ) == ()


def test_expiry_dynamic_hold_hysteresis_and_cutoff():
    s = Track8MacroRegimeMonthlyStrangle()
    s.evaluate(context(base()))

    hold = s.evaluate_expiry_cutoff(
        base(dte=Decimal("4"), current_price=Decimal("365"))
    )
    assert hold[0].direction == "HOLD_LONG_ATTACK"

    hysteresis = s.evaluate_expiry_cutoff(
        base(dte=Decimal("4"), current_price=Decimal("350"), active_vol=Decimal("1.0"))
    )
    assert hysteresis[0].direction == "HOLD_HYSTERESIS"

    cutoff = s.evaluate_expiry_cutoff(
        base(dte=Decimal("4"), current_price=Decimal("350"), active_vol=Decimal("1.0"))
    )
    assert cutoff[0].direction == "FLAT_STRANGLE"


def test_1515_pending_cancel():
    s = Track8MacroRegimeMonthlyStrangle()
    s.evaluate(context(base()))
    signals = s.evaluate_expiry_cutoff(
        base(time_str="15:15:01")
    )
    assert signals[0].direction == "CANCEL_PENDING_TRANCHES"


def test_strategy_id_mismatch_is_noop():
    s = Track8MacroRegimeMonthlyStrangle()
    bad_context = StrategyContext(
        strategy_id="other_strategy",
        input=StrategyInput(payload=base()),
    )
    assert s.evaluate(bad_context) == ()


def test_strategy_has_no_legacy_order_dependency():
    from core.strategy import track8_macro_regime_monthly_strangle
    source = inspect.getsource(track8_macro_regime_monthly_strangle)
    assert "OrderRequest" not in source
    assert "Broker" not in source
    assert "TimeService" not in source


def test_build_execution_plan_preserves_asymmetric_call_put_legs():
    s = Track8MacroRegimeMonthlyStrangle()
    assert s.build_execution_plan("G-8") is None

    s.evaluate(context(base(current_regime="HIGH_VOL")))
    plan = s.build_execution_plan("G-8")

    assert plan is not None
    assert plan.group_id == "G-8"
    assert plan.strategy_id == STRATEGY_ID
    assert len(plan.legs) == 2

    put_leg, call_leg = plan.legs
    assert put_leg.option_type == "PUT"
    assert put_leg.side == "BUY"
    assert put_leg.strike == s.state.put_strike
    assert put_leg.quantity == s.state.qty_put
    assert call_leg.option_type == "CALL"
    assert call_leg.side == "BUY"
    assert call_leg.strike == s.state.call_strike
    assert call_leg.quantity == s.state.qty_call
    assert put_leg.quantity == call_leg.quantity * 2
