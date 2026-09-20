"""Compose Strategy 5's canonical AnalyticsSnapshot."""
from __future__ import annotations

from contracts.analytics import AnalyticsProvenance, AnalyticsRequest, MarketSnapshot
from core.analytics.engine import AnalyticsEngine
from core.analytics.track5 import build_track5_evaluators


def build_track5_analytics_snapshot(data, *, run_id: str, as_of):
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
    return AnalyticsEngine(build_track5_evaluators()).evaluate(snapshot, requests)


__all__ = ("build_track5_analytics_snapshot",)
