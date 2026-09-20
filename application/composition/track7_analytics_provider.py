"""Compose Strategy 7's canonical AnalyticsSnapshot."""
from __future__ import annotations

from contracts.analytics import AnalyticsProvenance, AnalyticsRequest, MarketSnapshot
from core.analytics.engine import AnalyticsEngine
from core.analytics.track7 import build_track7_evaluators


def build_track7_analytics_snapshot(data, *, run_id: str, as_of):
    observations = {
        "current_price": data.price,
        "call_iv": data.option_iv,
        "put_iv": data.put_iv,
        "ma_1m": data.ma_1m,
        "ma_3m": data.ma_3m,
        "ma_5m": data.ma_5m,
        "ma_10m": data.ma_10m,
        "support": data.support,
        "resistance": data.resistance,
        "is_new_week_start": data.is_new_week_start,
        "is_expiry_day": data.is_expiry_day,
        "is_week_end": data.is_week_end,
        "order_timeout": data.order_timeout,
    }
    market = MarketSnapshot(
        run_id=run_id, as_of=as_of,
        provenance=AnalyticsProvenance(source="standard-runtime.track7"),
        instrument_identity=None, observations=observations,
    )
    keys = (
        ("price.last", ("current_price",)),
        ("options.call_iv", ("call_iv",)), ("options.put_iv", ("put_iv",)),
        ("options.skew", ("call_iv", "put_iv")),
        ("trend.ma_1m", ("ma_1m",)), ("trend.ma_3m", ("ma_3m",)),
        ("trend.ma_5m", ("ma_5m",)), ("trend.ma_10m", ("ma_10m",)),
        ("levels.support", ("support",)), ("levels.resistance", ("resistance",)),
        ("calendar.is_new_week_start", ("is_new_week_start",)),
        ("calendar.is_expiry_day", ("is_expiry_day",)),
        ("calendar.is_week_end", ("is_week_end",)),
        ("execution.order_timeout", ("order_timeout",)),
    )
    requests = tuple(AnalyticsRequest(k, "tick", 1, d, 1.0, "authoritative", "1") for k, d in keys)
    return AnalyticsEngine(build_track7_evaluators()).evaluate(market, requests)


__all__ = ("build_track7_analytics_snapshot",)
