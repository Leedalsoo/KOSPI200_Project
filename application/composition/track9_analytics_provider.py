"""Compose Strategy 9's canonical AnalyticsSnapshot."""
from __future__ import annotations

from decimal import Decimal

from contracts.analytics import AnalyticsProvenance, AnalyticsRequest, MarketSnapshot
from core.analytics.engine import AnalyticsEngine
from core.analytics.track9 import build_track9_evaluators


def build_track9_analytics_snapshot(
    data,
    *,
    run_id: str,
    as_of,
    total_fees=None,
    margin_ratio=None,
    option_contract_selection=None,
):
    """Build only from injected authoritative sources and observed runtime data."""
    observations = {
        "current_pnl": getattr(data, "current_pnl", None),
        "total_fees": total_fees,
        "margin_ratio": margin_ratio,
        "iv_spike": getattr(data, "iv_spike", None),
        "iv_crush": getattr(data, "iv_crush", None),
    }
    if option_contract_selection is not None:
        put = option_contract_selection.put
        call = option_contract_selection.call
        observations.update({
            "atm_put_strike": Decimal(str(put.strike)),
            "atm_call_strike": Decimal(str(call.strike)),
            "contract_multiplier": Decimal(str(put.contract_multiplier)),
        })
        if Decimal(str(call.contract_multiplier)) != observations["contract_multiplier"]:
            observations.pop("contract_multiplier", None)

    market = MarketSnapshot(
        run_id=run_id,
        as_of=as_of,
        provenance=AnalyticsProvenance(source="standard-runtime.track9"),
        instrument_identity=None,
        observations=observations,
    )
    definitions = {
        "portfolio.active_sell_qty": ("active_sell_qty",),
        "portfolio.insurance_qty": ("insurance_qty",),
        "events.upcoming": ("event_upcoming",),
        "options.iv_spike": ("iv_spike",),
        "options.iv_crush": ("iv_crush",),
        "portfolio.current_pnl": ("current_pnl",),
        "portfolio.total_fees": ("total_fees",),
        "portfolio.net_pnl": ("current_pnl", "total_fees"),
        "portfolio.margin_ratio": ("margin_ratio",),
        "risk.guard_active": ("risk_guard_active",),
        "portfolio.event_budget": ("event_budget",),
        "portfolio.estimated_event_cost": ("estimated_event_cost",),
        "options.atm_call_strike": ("atm_call_strike",),
        "options.atm_put_strike": ("atm_put_strike",),
        "options.contract_multiplier": ("contract_multiplier",),
        "portfolio.premium_spent": ("premium_spent",),
    }
    requests = tuple(
        AnalyticsRequest(key, "tick", 1, dependencies, 1.0, "authoritative", "1")
        for key, dependencies in definitions.items()
    )
    return AnalyticsEngine(build_track9_evaluators()).evaluate(market, requests)


__all__ = ("build_track9_analytics_snapshot",)
