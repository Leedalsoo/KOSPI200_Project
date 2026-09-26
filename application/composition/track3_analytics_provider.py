"""Compose Strategy 3's canonical AnalyticsSnapshot."""
from __future__ import annotations

from datetime import datetime

from contracts.analytics import AnalyticsProvenance, AnalyticsRequest, MarketSnapshot
from core.analytics.engine import AnalyticsEngine
from core.analytics.track3 import build_track3_evaluators
from core.analytics.common import COMMON_METRIC_CONTRACTS, merge_analytics_snapshots


def build_track3_analytics_snapshot(data, *, run_id: str, current_pnl: float | None = None, as_of, common_snapshot=None):
    observations = {
        "spread_history": data.spread_history,
        "active_vol": data.active_vol,
        "base_vol": data.base_vol,
        "price_change_rate": data.price_change_rate,
        "bid_ask_spread": data.bid_ask_spread,
        "gap_pct": data.gap_pct,
        "total_fees": data.total_fees,
        "current_pnl": current_pnl,
        "premium_spent": data.premium_spent,
        "options_legs": data.options_legs,
    }
    observations = {k: v for k, v in observations.items() if v is not None}
    snapshot = MarketSnapshot(
        run_id=run_id, as_of=as_of,
        provenance=AnalyticsProvenance(source="standard-runtime.track3"),
        instrument_identity=None, observations=observations,
    )
    keys = (
        ("spread.z_score", ("spread_history",)),
        ("spread.std", ("spread_history",)),
        ("volatility.active", ("active_vol",)),
        ("volatility.base", ("base_vol",)),
        ("volatility.ratio", ("active_vol", "base_vol")),
        ("price.change_rate", ("price_change_rate",)),
        ("microstructure.spread", ("bid_ask_spread",)),
        ("market.gap_pct", ("gap_pct",)),
        ("cost.fees", ("total_fees",)),
        ("portfolio.current_pnl", ("current_pnl",)),
        ("portfolio.options_pnl", ("options_legs",)),
        ("portfolio.premium_spent", ("premium_spent",)),
    )
    common_keys = set(COMMON_METRIC_CONTRACTS) if common_snapshot is not None else set()
    requests = tuple(AnalyticsRequest(k, "tick", 1 if common_snapshot is not None else 20, d, 1.0, "authoritative", "1") for k, d in keys if k not in common_keys)
    if not requests:
        return common_snapshot
    strategy_snapshot = AnalyticsEngine(build_track3_evaluators()).evaluate(snapshot, requests)
    return merge_analytics_snapshots(common_snapshot, strategy_snapshot) if common_snapshot is not None else strategy_snapshot
