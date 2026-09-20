from datetime import datetime
from decimal import Decimal
from contracts.analytics import AnalyticsProvenance, AnalyticsRequest, MarketSnapshot
from core.analytics.engine import AnalyticsEngine
from core.analytics.track8 import build_track8_evaluators
from core.strategy.contracts import CommonStrategyInput, StrategyContext, StrategyInput
from core.strategy.track8_macro_regime_monthly_strangle import Track8MacroRegimeMonthlyStrangle


def context(**obs):
    base = dict(price=Decimal("350"), dte=Decimal("20"), current_regime="NORMAL", active_vol=Decimal("1"), current_pnl=Decimal("400000"), total_fees=Decimal("10000"), margin_ratio=Decimal("0.2"), risk_guard_active=False, call_iv=Decimal("12"), put_iv=Decimal("13"), atm_iv=Decimal("12.5"), call_strike=Decimal("365"), put_strike=Decimal("335"), call_contract_multiplier=Decimal("250000"), put_contract_multiplier=Decimal("250000"))
    base.update(obs)
    m = MarketSnapshot("t8", obs.pop("as_of", datetime(2026,9,18,10)), AnalyticsProvenance("test"), None, base)
    deps = {"options.dte":("dte",),"options.call_iv":("call_iv",),"options.put_iv":("put_iv",),"options.atm_iv":("atm_iv",),"options.call_strike":("call_strike",),"options.put_strike":("put_strike",),"options.call_contract_multiplier":("call_contract_multiplier",),"options.put_contract_multiplier":("put_contract_multiplier",),"options.moneyness":("price","call_strike","put_strike"),"market.current_regime":("current_regime",),"volatility.active":("active_vol",),"portfolio.current_pnl":("current_pnl",),"portfolio.total_fees":("total_fees",),"portfolio.net_pnl":("current_pnl","total_fees"),"portfolio.margin_ratio":("margin_ratio",),"risk.guard_active":("risk_guard_active",)}
    a = AnalyticsEngine(build_track8_evaluators()).evaluate(m, tuple(AnalyticsRequest(k,"tick",1,d,1.0,"authoritative","1") for k,d in deps.items()))
    common = CommonStrategyInput(as_of=m.as_of,current_price=base["price"],active_vol=base["active_vol"],base_vol=None,budget=Decimal("2000000"),current_pnl=base["current_pnl"],total_fees=base["total_fees"],time_str="10:00:00",date_str="2026-09-18")
    return StrategyContext(strategy_id=Track8MacroRegimeMonthlyStrangle.strategy_id,input=StrategyInput(common),analytics=a)


def test_entry_consumes_authoritative_strikes_and_multiplier():
    s=Track8MacroRegimeMonthlyStrangle(); out=s.evaluate(context())
    assert out and s.state.call_strike==Decimal("365") and s.state.put_strike==Decimal("335")


def test_missing_contract_inputs_fail_closed():
    s=Track8MacroRegimeMonthlyStrangle(); assert s.evaluate(context(call_strike=None))==()


def test_regime_signal_is_strategy_owned():
    s=Track8MacroRegimeMonthlyStrangle(); assert s.evaluate_macro_regime_protection(context(current_regime="CRASH"))[0].direction=="MACRO_HEDGE_SCALE_UP"
