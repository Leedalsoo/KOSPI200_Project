"""Compose Strategy 2's canonical AnalyticsSnapshot from runtime observations."""
from __future__ import annotations

from contracts.analytics import AnalyticsProvenance, AnalyticsRequest, MarketSnapshot
from core.analytics.engine import AnalyticsEngine
from core.analytics.track2 import build_track2_evaluators


def build_track2_analytics_snapshot(data, *, run_id: str):
    observations = {
        "bbw_window": data.bbw_window,
        "volume_window": data.volume_window,
        "basis": data.basis,
        "put_iv": data.put_iv,
        "call_iv": data.option_iv,
        "poc_price": data.poc_price,
        "bid_qtys": data.option_bid_qtys,
        "ask_qtys": data.option_ask_qtys,
        "active_vol": data.active_vol,
        "base_vol": data.base_vol,
    }
    if any(value is None for value in observations.values()):
        return None
    snapshot = MarketSnapshot(
        run_id=run_id,
        as_of=data.as_of,
        provenance=AnalyticsProvenance(source="standard-runtime.track2"),
        instrument_identity=None,
        observations=observations,
    )
    keys = (
        ("volatility.bbw", ("bbw_window",)),
        ("volume.z_score", ("volume_window",)),
        ("microstructure.obi", ("bid_qtys", "ask_qtys")),
        ("futures.basis", ("basis",)),
        ("options.put_iv", ("put_iv",)),
        ("options.call_iv", ("call_iv",)),
        ("volume_profile.poc", ("poc_price",)),
        ("volatility.active", ("active_vol",)),
        ("volatility.base", ("base_vol",)),
    )
    requests = tuple(
        AnalyticsRequest(
            metric_key=key,
            timeframe="tick",
            window=20,
            dependencies=deps,
            freshness_seconds=1.0,
            source_requirement="authoritative",
            analytics_version="1",
        )
        for key, deps in keys
    )
    return AnalyticsEngine(build_track2_evaluators()).evaluate(snapshot, requests)
