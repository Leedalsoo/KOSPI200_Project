from decimal import Decimal
from core.strategy.track8_macro_regime_monthly_strangle import Track8MacroRegimeMonthlyStrangle
from tests.unit.test_track8_common_analytics_strategy import context


def test_monthly_entry_via_standard_context():
    s=Track8MacroRegimeMonthlyStrangle(); signals=s.evaluate(context())
    assert signals and s.state.call_strike==Decimal("365") and s.state.put_strike==Decimal("335")

def test_dte_and_budget_guards():
    s=Track8MacroRegimeMonthlyStrangle(); assert s.evaluate(context(dte=Decimal("14.9")))==()

def test_high_vol_asymmetric_qty():
    s=Track8MacroRegimeMonthlyStrangle(); s.evaluate(context(current_regime="HIGH_VOL")); assert s.state.qty_put==2*s.state.qty_call

def test_macro_regime_hedge_signal():
    s=Track8MacroRegimeMonthlyStrangle(); assert s.evaluate_macro_regime_protection(context(current_regime="CRASH"))

def test_profit_rebuild_and_risk_guard():
    s=Track8MacroRegimeMonthlyStrangle(); s.evaluate(context()); assert len(s.evaluate_profit_rebuild(context()))==2

def test_expiry_requires_analytics():
    s=Track8MacroRegimeMonthlyStrangle(); assert s.evaluate_expiry_cutoff(context(dte=Decimal("4")))==()

def test_1515_pending_cancel():
    s=Track8MacroRegimeMonthlyStrangle(); s.state=s.state.__class__(is_active=True, call_strike=Decimal('365'), put_strike=Decimal('335'), qty_call=1, qty_put=2)
    c=context(as_of=__import__('datetime').datetime(2026,9,18,15,15,1), dte=Decimal('5'))
    s.state = s.state.__class__(is_active=True, call_strike=Decimal('365'), put_strike=Decimal('335'), qty_call=1, qty_put=2)
    assert s.evaluate_expiry_cutoff(c)[0].direction == "CANCEL_PENDING_TRANCHES"

def test_strategy_id_mismatch_is_noop():
    from dataclasses import replace
    s=Track8MacroRegimeMonthlyStrangle(); c=context()
    assert s.evaluate(replace(c, strategy_id="other"))==()

def test_build_execution_plan_preserves_legs():
    s=Track8MacroRegimeMonthlyStrangle(); assert s.build_execution_plan("G-8") is None; s.evaluate(context(current_regime="HIGH_VOL")); plan=s.build_execution_plan("G-8")
    assert plan and len(plan.legs)==2 and plan.legs[0].quantity==2*plan.legs[1].quantity
