"""Compose Strategy 6's canonical AnalyticsSnapshot."""
from __future__ import annotations

from contracts.analytics import AnalyticsProvenance, AnalyticsRequest, MarketSnapshot
from core.analytics.engine import AnalyticsEngine
from core.analytics.track6 import build_track6_evaluators
from core.analytics.common import COMMON_METRIC_CONTRACTS, merge_analytics_snapshots


def build_track6_analytics_snapshot(data, *, run_id: str, as_of, common_snapshot=None):
    observations = {
        "current_price": data.price,
        "active_vol": data.active_vol,
        "base_vol": data.base_vol,
        "premium_spent": getattr(data, "premium_spent", None),
    }
    snapshot = MarketSnapshot(
        run_id=run_id,
        as_of=as_of,
        provenance=AnalyticsProvenance(source="standard-runtime.track6"),
        instrument_identity=None,
        observations=observations,
    )
    keys = (
        ("price.last", ("current_price",)),
        ("volatility.active", ("active_vol",)),
        ("volatility.base", ("base_vol",)),
        ("volatility.ratio", ("active_vol", "base_vol")),
        ("portfolio.premium_spent", ("premium_spent",)),
    )
    requests = tuple(
        AnalyticsRequest(key, "tick", 1, dependencies, 1.0, "authoritative", "1")
        for key, dependencies in keys
    )
    common_keys = set(COMMON_METRIC_CONTRACTS) if common_snapshot is not None else set()
    requests = tuple(request for request in requests if request.metric_key not in common_keys)
    if not requests:
        return common_snapshot
    strategy_snapshot = AnalyticsEngine(build_track6_evaluators()).evaluate(snapshot, requests)
    return merge_analytics_snapshots(common_snapshot, strategy_snapshot) if common_snapshot is not None else strategy_snapshot


__all__ = ("build_track6_analytics_snapshot",)
