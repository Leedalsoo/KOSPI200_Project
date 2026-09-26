"""Compose Strategy 5's canonical AnalyticsSnapshot."""
from __future__ import annotations

from contracts.analytics import AnalyticsProvenance, AnalyticsRequest, MarketSnapshot
from core.analytics.engine import AnalyticsEngine
from core.analytics.track5 import build_track5_evaluators
from core.analytics.common import COMMON_METRIC_CONTRACTS, merge_analytics_snapshots


def build_track5_analytics_snapshot(data, *, run_id: str, as_of, common_snapshot=None):
    observations = {
        "open_price": data.open_price,
        "previous_close": data.previous_close,
        "current_price": data.price,
        "active_vol": data.active_vol,
        "regime": data.macro_regime,
    }
    snapshot = MarketSnapshot(
        run_id=run_id,
        as_of=as_of,
        provenance=AnalyticsProvenance(source="standard-runtime.track5"),
        instrument_identity=None,
        observations=observations,
    )
    keys = (
        ("price.open", ("open_price",)),
        ("price.gap", ("open_price", "previous_close")),
        ("price.gap_pct", ("open_price", "previous_close")),
        ("price.last", ("current_price",)),
        ("price.previous_close", ("previous_close",)),
        ("volatility.active", ("active_vol",)),
        ("volatility.expected_move", ("previous_close", "active_vol")),
        ("stats.z_score", ("open_price", "previous_close", "active_vol")),
        ("regime.market", ("regime",)),
    )
    requests = tuple(
        AnalyticsRequest(key, "tick", 1, dependencies, 1.0, "authoritative", "1")
        for key, dependencies in keys
    )
    common_keys = set(COMMON_METRIC_CONTRACTS) if common_snapshot is not None else set()
    requests = tuple(request for request in requests if request.metric_key not in common_keys)
    if not requests:
        return common_snapshot
    strategy_snapshot = AnalyticsEngine(build_track5_evaluators()).evaluate(snapshot, requests)
    return merge_analytics_snapshots(common_snapshot, strategy_snapshot) if common_snapshot is not None else strategy_snapshot


__all__ = ("build_track5_analytics_snapshot",)
