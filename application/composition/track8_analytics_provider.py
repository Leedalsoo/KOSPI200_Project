"""Compose Strategy 8's canonical AnalyticsSnapshot."""
from __future__ import annotations
from contracts.analytics import AnalyticsProvenance, AnalyticsRequest, MarketSnapshot
from core.analytics.engine import AnalyticsEngine
from core.analytics.track8 import build_track8_evaluators


def build_track8_analytics_snapshot(data, *, run_id: str, as_of):
    observations = {
        "current_price": data.price, "dte": data.days_to_expiry, "current_regime": data.macro_regime,
        "active_vol": data.active_vol, "current_pnl": getattr(data, "current_pnl", None), "total_fees": getattr(data, "total_fees", None),
        "margin_ratio": getattr(data, "margin_ratio", None), "risk_guard_active": getattr(data, "risk_guard_active", None),
        "call_iv": data.option_iv, "put_iv": data.put_iv, "atm_iv": data.option_iv,
        "call_strike": getattr(data, "call_strike", None), "put_strike": getattr(data, "put_strike", None),
        "call_contract_multiplier": getattr(data, "call_contract_multiplier", None),
        "put_contract_multiplier": getattr(data, "put_contract_multiplier", None),
    }
    market = MarketSnapshot(run_id=run_id, as_of=as_of,
        provenance=AnalyticsProvenance(source="standard-runtime.track8"), instrument_identity=None,
        observations=observations)
    defs = {
        "options.dte": ("dte",), "options.call_iv": ("call_iv",), "options.put_iv": ("put_iv",),
        "options.atm_iv": ("atm_iv",), "options.call_strike": ("call_strike",),
        "options.put_strike": ("put_strike",), "options.call_contract_multiplier": ("call_contract_multiplier",),
        "options.put_contract_multiplier": ("put_contract_multiplier",),
        "options.moneyness": ("current_price", "call_strike", "put_strike"),
        "market.current_regime": ("current_regime",), "volatility.active": ("active_vol",),
        "portfolio.current_pnl": ("current_pnl",), "portfolio.total_fees": ("total_fees",),
        "portfolio.net_pnl": ("current_pnl", "total_fees"), "portfolio.margin_ratio": ("margin_ratio",),
        "risk.guard_active": ("risk_guard_active",),
    }
    requests = tuple(AnalyticsRequest(k, "tick", 1, deps, 1.0, "authoritative", "1") for k, deps in defs.items())
    return AnalyticsEngine(build_track8_evaluators()).evaluate(market, requests)


__all__ = ("build_track8_analytics_snapshot",)
