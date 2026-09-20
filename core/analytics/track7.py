"""Common Analytics evaluators required by Strategy 7."""
from __future__ import annotations

from decimal import Decimal
from typing import Mapping

from contracts.analytics import AnalyticsMetric, AnalyticsProvenance, AnalyticsRequest, AnalyticsStatus, MarketSnapshot


def _metric(request, snapshot, value, unit):
    return AnalyticsMetric(request.metric_key, value, AnalyticsStatus.AVAILABLE, unit,
                           snapshot.as_of, request.analytics_version,
                           (AnalyticsProvenance(source="common-analytics.track7", dependencies=request.dependencies, source_as_of=snapshot.as_of),))


def _unavailable(request, snapshot, unit):
    return AnalyticsMetric(request.metric_key, None, AnalyticsStatus.UNAVAILABLE, unit,
                           snapshot.as_of, request.analytics_version,
                           (AnalyticsProvenance(source="common-analytics.track7", dependencies=request.dependencies, source_as_of=snapshot.as_of),))


def _passthrough(key, unit):
    def evaluator(snapshot, request):
        value = snapshot.observations.get(key)
        return _unavailable(request, snapshot, unit) if value is None else _metric(request, snapshot, value, unit)
    return evaluator


def _skew(snapshot, request):
    call_iv = snapshot.observations.get("call_iv")
    put_iv = snapshot.observations.get("put_iv")
    if call_iv is None or put_iv is None:
        return _unavailable(request, snapshot, "iv-points")
    return _metric(request, snapshot, Decimal(str(put_iv)) - Decimal(str(call_iv)), "iv-points")


def build_track7_evaluators() -> Mapping[str, object]:
    return {
        "price.last": _passthrough("current_price", "index-points"),
        "options.call_iv": _passthrough("call_iv", "iv-points"),
        "options.put_iv": _passthrough("put_iv", "iv-points"),
        "options.skew": _skew,
        "trend.ma_1m": _passthrough("ma_1m", "index-points"),
        "trend.ma_3m": _passthrough("ma_3m", "index-points"),
        "trend.ma_5m": _passthrough("ma_5m", "index-points"),
        "trend.ma_10m": _passthrough("ma_10m", "index-points"),
        "levels.support": _passthrough("support", "index-points"),
        "levels.resistance": _passthrough("resistance", "index-points"),
        "calendar.is_new_week_start": _passthrough("is_new_week_start", "bool"),
        "calendar.is_expiry_day": _passthrough("is_expiry_day", "bool"),
        "calendar.is_week_end": _passthrough("is_week_end", "bool"),
        "execution.order_timeout": _passthrough("order_timeout", "bool"),
    }


__all__ = ("build_track7_evaluators",)
