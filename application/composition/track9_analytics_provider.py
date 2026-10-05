"""Compose Strategy 9's canonical AnalyticsSnapshot."""
from __future__ import annotations

from decimal import Decimal

from contracts.analytics import AnalyticsProvenance, AnalyticsRequest, MarketSnapshot
from core.analytics.engine import AnalyticsEngine
from core.analytics.track9 import build_track9_evaluators
from core.analytics.common import COMMON_METRIC_CONTRACTS, merge_analytics_snapshots


def build_track9_analytics_snapshot(
    data,
    *,
    run_id: str,
    as_of,
    total_fees=None,
    margin_ratio=None,
    option_contract_selection=None,
    common_snapshot=None,
    active_sell_qty=None,
    insurance_qty=None,
    event_upcoming=None,
    event_budget=None,
    estimated_event_cost=None,
    premium_spent=None,
    option_prices=None,
):
    """Build Track9-specific analytics and merge canonical Common Analytics."""
    observations = {
        "iv_spike": getattr(data, "iv_spike", None),
        "iv_crush": getattr(data, "iv_crush", None),
    }
    observations.update({
        "active_sell_qty": active_sell_qty,
        "insurance_qty": insurance_qty,
        "event_upcoming": event_upcoming,
        "event_budget": event_budget,
        "estimated_event_cost": estimated_event_cost,
        "premium_spent": premium_spent,
        "track9_put_entry_price": (option_prices or {}).get("put_entry_price"),
        "track9_call_entry_price": (option_prices or {}).get("call_entry_price"),
        "track9_put_mark_price": (option_prices or {}).get("put_mark_price"),
        "track9_call_mark_price": (option_prices or {}).get("call_mark_price"),
    })
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
        "portfolio.event_budget": ("event_budget",),
        "portfolio.estimated_event_cost": ("estimated_event_cost",),
        "options.atm_call_strike": ("atm_call_strike",),
        "options.atm_put_strike": ("atm_put_strike",),
        "options.contract_multiplier": ("contract_multiplier",),
        "portfolio.premium_spent": ("premium_spent",),
        "options.track9_put_entry_price": ("track9_put_entry_price",),
        "options.track9_call_entry_price": ("track9_call_entry_price",),
        "options.track9_put_mark_price": ("track9_put_mark_price",),
        "options.track9_call_mark_price": ("track9_call_mark_price",),
    }
    requests = tuple(
        AnalyticsRequest(key, "tick", 1, dependencies, 1.0, "authoritative", "1")
        for key, dependencies in definitions.items()
    )
    common_keys = set(COMMON_METRIC_CONTRACTS) if common_snapshot is not None else set()
    requests = tuple(request for request in requests if request.metric_key not in common_keys)
    if not requests:
        return common_snapshot
    strategy_snapshot = AnalyticsEngine(build_track9_evaluators()).evaluate(market, requests)
    return merge_analytics_snapshots(common_snapshot, strategy_snapshot) if common_snapshot is not None else strategy_snapshot


__all__ = ("build_track9_analytics_snapshot",)
