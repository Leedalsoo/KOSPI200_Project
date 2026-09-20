"""Compose Strategy 6's canonical AnalyticsSnapshot."""
from __future__ import annotations

from contracts.analytics import AnalyticsProvenance, AnalyticsRequest, MarketSnapshot
from core.analytics.engine import AnalyticsEngine
from core.analytics.track6 import build_track6_evaluators


def build_track6_analytics_snapshot(data, *, run_id: str, as_of):
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
    return AnalyticsEngine(build_track6_evaluators()).evaluate(snapshot, requests)


__all__ = ("build_track6_analytics_snapshot",)
