from datetime import datetime
from decimal import Decimal
from contracts.analytics import AnalyticsProvenance, AnalyticsRequest, MarketSnapshot, AnalyticsStatus
from core.analytics.engine import AnalyticsEngine
from core.analytics.track8 import build_track8_evaluators
from core.strategy.track8_macro_regime_monthly_strangle import Track8MacroRegimeMonthlyStrangle


def snap(**values):
    base = dict(current_price=Decimal("350"), dte=Decimal("20"), current_regime="NORMAL", active_vol=Decimal("1"),
                current_pnl=Decimal("0"), total_fees=Decimal("0"), margin_ratio=Decimal("0.2"), risk_guard_active=False,
                call_iv=Decimal("12"), put_iv=Decimal("13"), atm_iv=Decimal("12.5"), call_strike=Decimal("365"),
                put_strike=Decimal("335"), call_contract_multiplier=Decimal("250000"), put_contract_multiplier=Decimal("250000"))
    base.update(values)
    return MarketSnapshot("track8-test", datetime(2026, 9, 18, 10), AnalyticsProvenance("test"), None, base)


def evaluate(s):
    deps = {
        "options.dte": ("dte",), "options.call_iv": ("call_iv",), "options.put_iv": ("put_iv",), "options.atm_iv": ("atm_iv",),
        "options.call_strike": ("call_strike",), "options.put_strike": ("put_strike",),
        "options.call_contract_multiplier": ("call_contract_multiplier",), "options.put_contract_multiplier": ("put_contract_multiplier",),
        "options.moneyness": ("current_price", "call_strike", "put_strike"), "market.current_regime": ("current_regime",),
        "volatility.active": ("active_vol",), "portfolio.current_pnl": ("current_pnl",), "portfolio.total_fees": ("total_fees",),
        "portfolio.net_pnl": ("current_pnl", "total_fees"), "portfolio.margin_ratio": ("margin_ratio",), "risk.guard_active": ("risk_guard_active",),
    }
    req = tuple(AnalyticsRequest(k, "tick", 1, d, 1.0, "authoritative", "1") for k, d in deps.items())
    return AnalyticsEngine(build_track8_evaluators()).evaluate(s, req)


def test_common_analytics_calculates_net_pnl_and_moneyness():
    r = evaluate(snap(current_pnl=Decimal("400000"), total_fees=Decimal("10000")))
    assert r.get("portfolio.net_pnl").value == Decimal("390000")
    assert r.get("options.moneyness").value["call_distance"] == Decimal("-15")


def test_common_analytics_is_fail_closed_when_source_missing():
    r = evaluate(snap(dte=None))
    assert r.get("options.dte").status is AnalyticsStatus.UNAVAILABLE
    assert r.get("options.dte").value is None


def test_strategy_has_no_legacy_calculation_constants():
    import inspect
    source = inspect.getsource(Track8MacroRegimeMonthlyStrangle)
    assert "STRIKE_OFFSET" not in source
    assert "MULTIPLIER =" not in source
    assert "atm_strike" not in source
