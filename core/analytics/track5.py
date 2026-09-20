"""Common Analytics evaluators required by Strategy 5."""
from __future__ import annotations

from decimal import Decimal
from typing import Mapping

from contracts.analytics import AnalyticsMetric, AnalyticsProvenance, AnalyticsRequest, AnalyticsStatus, MarketSnapshot


def _metric(request, snapshot, value, unit):
    return AnalyticsMetric(
        request.metric_key, value, AnalyticsStatus.AVAILABLE, unit,
        snapshot.as_of, request.analytics_version,
        (AnalyticsProvenance(source="common-analytics.track5", dependencies=request.dependencies, source_as_of=snapshot.as_of),),
    )


def _unavailable(request, snapshot, unit):
    return AnalyticsMetric(
        request.metric_key, None, AnalyticsStatus.UNAVAILABLE, unit,
        snapshot.as_of, request.analytics_version,
        (AnalyticsProvenance(source="common-analytics.track5", dependencies=request.dependencies, source_as_of=snapshot.as_of),),
    )


def _gap(snapshot, request):
    open_price = Decimal(str(snapshot.observations["open_price"]))
    previous_close = Decimal(str(snapshot.observations["previous_close"]))
    return _metric(request, snapshot, open_price - previous_close, "index-points")


def _gap_pct(snapshot, request):
    previous_close = Decimal(str(snapshot.observations["previous_close"]))
    if previous_close <= 0:
        return _unavailable(request, snapshot, "ratio")
    gap = Decimal(str(snapshot.observations["open_price"])) - previous_close
    return _metric(request, snapshot, gap / previous_close, "ratio")


def _expected_move(snapshot, request):
    previous_close_raw = snapshot.observations.get("previous_close")
    active_vol_raw = snapshot.observations.get("active_vol")
    if previous_close_raw is None or active_vol_raw is None:
        return _unavailable(request, snapshot, "index-points")
    previous_close = Decimal(str(previous_close_raw))
    active_vol = Decimal(str(active_vol_raw))
    if previous_close <= 0 or active_vol < 0:
        return _unavailable(request, snapshot, "index-points")
    return _metric(
        request, snapshot,
        previous_close * (Decimal("0.15") / Decimal("15.874507866")) * active_vol,
        "index-points",
    )


def _z_score(snapshot, request):
    expected = _expected_move(snapshot, request)
    if expected.value is None or expected.value <= 0:
        return _unavailable(request, snapshot, "zscore")
    gap = Decimal(str(snapshot.observations["open_price"])) - Decimal(str(snapshot.observations["previous_close"]))
    return _metric(request, snapshot, gap / max(Decimal("0.1"), expected.value), "zscore")


def _passthrough(key, unit):
    def evaluator(snapshot, request):
        value = snapshot.observations.get(key)
        return _unavailable(request, snapshot, unit) if value is None else _metric(request, snapshot, value, unit)
    return evaluator


def build_track5_evaluators() -> Mapping[str, object]:
    return {
        "price.open": _passthrough("open_price", "index-points"),
        "price.gap": _gap,
        "price.gap_pct": _gap_pct,
        "price.last": _passthrough("current_price", "index-points"),
        "price.previous_close": _passthrough("previous_close", "index-points"),
        "volatility.active": _passthrough("active_vol", "decimal"),
        "volatility.expected_move": _expected_move,
        "stats.z_score": _z_score,
        "regime.market": _passthrough("regime", "enum"),
    }


__all__ = ("build_track5_evaluators",)
