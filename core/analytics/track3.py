"""Common Analytics evaluators required by Strategy 3."""
from __future__ import annotations

from math import isfinite
from statistics import mean, pstdev
from typing import Mapping

from contracts.analytics import AnalyticsMetric, AnalyticsProvenance, AnalyticsRequest, AnalyticsStatus, MarketSnapshot


def _metric(request, snapshot, value, unit):
    return AnalyticsMetric(
        metric_key=request.metric_key, value=value,
        status=AnalyticsStatus.AVAILABLE, unit=unit,
        as_of=snapshot.as_of, calculation_version=request.analytics_version,
        provenance=(AnalyticsProvenance(source="common-analytics.track3", dependencies=request.dependencies),),
    )


def _z_score(snapshot, request):
    values = tuple(float(v) for v in snapshot.observations["spread_history"])
    if len(values) < 10 or not all(isfinite(v) for v in values):
        return AnalyticsMetric(request.metric_key, None, AnalyticsStatus.UNAVAILABLE, "zscore", snapshot.as_of, request.analytics_version, ())
    std = pstdev(values)
    value = 0.0 if std == 0.0 else (values[-1] - mean(values)) / std
    return _metric(request, snapshot, value, "zscore")


def _spread_std(snapshot, request):
    values = tuple(float(v) for v in snapshot.observations["spread_history"])
    if len(values) < 10 or not all(isfinite(v) for v in values):
        return AnalyticsMetric(request.metric_key, None, AnalyticsStatus.UNAVAILABLE, "index-points", snapshot.as_of, request.analytics_version, ())
    return _metric(request, snapshot, pstdev(values), "index-points")


def _vol_ratio(snapshot, request):
    active = float(snapshot.observations["active_vol"])
    base = float(snapshot.observations["base_vol"])
    if not isfinite(active) or not isfinite(base) or active <= 0 or base <= 0:
        return AnalyticsMetric(request.metric_key, None, AnalyticsStatus.UNAVAILABLE, "ratio", snapshot.as_of, request.analytics_version, ())
    return _metric(request, snapshot, active / base, "ratio")


def _passthrough(key, unit):
    def evaluator(snapshot, request):
        return _metric(request, snapshot, snapshot.observations[key], unit)
    return evaluator


def _options_pnl(snapshot, request):
    total = 0.0
    for leg in snapshot.observations["options_legs"]:
        multiplier = leg.get("contract_multiplier")
        if multiplier is None or float(multiplier) <= 0:
            return AnalyticsMetric(request.metric_key, None, AnalyticsStatus.BLOCKED, "currency", snapshot.as_of, request.analytics_version, ())
        entry = float(leg["price"])
        market = leg.get("current_market_price")
        if market is None:
            return AnalyticsMetric(request.metric_key, None, AnalyticsStatus.UNAVAILABLE, "currency", snapshot.as_of, request.analytics_version, ())
        qty = int(leg["qty"])
        side = str(leg["side"])
        total += (float(market) - entry if side == "BUY" else entry - float(market)) * qty * float(multiplier)
    return _metric(request, snapshot, total, "currency")


def build_track3_evaluators() -> Mapping[str, object]:
    return {
        "spread.z_score": _z_score,
        "spread.std": _spread_std,
        "volatility.active": _passthrough("active_vol", "decimal"),
        "volatility.base": _passthrough("base_vol", "decimal"),
        "volatility.ratio": _vol_ratio,
        "price.change_rate": _passthrough("price_change_rate", "ratio"),
        "microstructure.spread": _passthrough("bid_ask_spread", "index-points"),
        "market.gap_pct": _passthrough("gap_pct", "ratio"),
        "cost.fees": _passthrough("total_fees", "currency"),
        "portfolio.current_pnl": _passthrough("current_pnl", "currency"),
        "portfolio.options_pnl": _options_pnl,
        "portfolio.premium_spent": _passthrough("premium_spent", "currency"),
    }


__all__ = ("build_track3_evaluators",)
