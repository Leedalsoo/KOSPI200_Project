"""Common Analytics evaluators required by Strategy 6."""
from __future__ import annotations

from decimal import Decimal
from typing import Mapping

from contracts.analytics import (
    AnalyticsMetric,
    AnalyticsProvenance,
    AnalyticsRequest,
    AnalyticsStatus,
    MarketSnapshot,
)


def _metric(request, snapshot, value, unit):
    return AnalyticsMetric(
        request.metric_key, value, AnalyticsStatus.AVAILABLE, unit,
        snapshot.as_of, request.analytics_version,
        (AnalyticsProvenance(source="common-analytics.track6", dependencies=request.dependencies, source_as_of=snapshot.as_of),),
    )


def _unavailable(request, snapshot, unit):
    return AnalyticsMetric(
        request.metric_key, None, AnalyticsStatus.UNAVAILABLE, unit,
        snapshot.as_of, request.analytics_version,
        (AnalyticsProvenance(source="common-analytics.track6", dependencies=request.dependencies, source_as_of=snapshot.as_of),),
    )


def _passthrough(key, unit):
    def evaluator(snapshot, request):
        value = snapshot.observations.get(key)
        return _unavailable(request, snapshot, unit) if value is None else _metric(request, snapshot, value, unit)
    return evaluator


def _volatility_ratio(snapshot, request):
    active_raw = snapshot.observations.get("active_vol")
    base_raw = snapshot.observations.get("base_vol")
    if active_raw is None or base_raw is None:
        return _unavailable(request, snapshot, "ratio")
    active = Decimal(str(active_raw))
    base = Decimal(str(base_raw))
    if active < 0 or base <= 0:
        return _unavailable(request, snapshot, "ratio")
    return _metric(request, snapshot, active / base, "ratio")


def build_track6_evaluators() -> Mapping[str, object]:
    return {
        "price.last": _passthrough("current_price", "index-points"),
        "volatility.active": _passthrough("active_vol", "decimal"),
        "volatility.base": _passthrough("base_vol", "decimal"),
        "volatility.ratio": _volatility_ratio,
        "portfolio.premium_spent": _passthrough("premium_spent", "KRW"),
    }


__all__ = ("build_track6_evaluators",)
