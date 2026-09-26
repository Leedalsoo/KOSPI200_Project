"""Compose Strategy 4's canonical AnalyticsSnapshot."""
from __future__ import annotations

from contracts.analytics import AnalyticsProvenance, AnalyticsRequest, MarketSnapshot
from core.analytics.engine import AnalyticsEngine
from core.analytics.track4 import build_track4_evaluators
from core.analytics.common import COMMON_METRIC_CONTRACTS, merge_analytics_snapshots


def build_track4_analytics_snapshot(data, *, run_id: str, as_of, common_snapshot=None):
    observations = {
        "active_vol": data.active_vol,
        "base_vol": data.base_vol,
        "current_delta": data.current_delta,
        "current_gamma": data.current_gamma,
        "current_theta": data.current_theta,
        "current_pnl": data.current_pnl,
        "current_equity": data.current_equity,
        "price_history": data.price_history,
    }
    premium_spent = getattr(data, "premium_spent", None)
    if premium_spent is not None:
        observations["premium_spent"] = premium_spent
    snapshot = MarketSnapshot(
        run_id=run_id,
        as_of=as_of,
        provenance=AnalyticsProvenance(source="standard-runtime.track4"),
        instrument_identity=None,
        observations=observations,
    )
    keys = (
        ("volatility.active", ("active_vol",)),
        ("volatility.base", ("base_vol",)),
        ("volatility.ratio", ("active_vol", "base_vol")),
        ("options.delta", ("current_delta",)),
        ("options.gamma", ("current_gamma",)),
        ("options.theta", ("current_theta",)),
        ("portfolio.current_pnl", ("current_pnl",)),
        ("portfolio.equity", ("current_equity",)),
        ("price.tick_deadband", ("price_history",)),
    )
    if "premium_spent" in observations:
        keys += (("portfolio.premium_spent", ("premium_spent",)),)
    requests = tuple(
        AnalyticsRequest(key, "tick", 1, dependencies, 1.0, "authoritative", "1")
        for key, dependencies in keys
    )
    common_keys = set(COMMON_METRIC_CONTRACTS) if common_snapshot is not None else set()
    requests = tuple(request for request in requests if request.metric_key not in common_keys)
    if not requests:
        return common_snapshot
    strategy_snapshot = AnalyticsEngine(build_track4_evaluators()).evaluate(snapshot, requests)
    return merge_analytics_snapshots(common_snapshot, strategy_snapshot) if common_snapshot is not None else strategy_snapshot
