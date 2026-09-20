"""Common Analytics evaluators required by Strategy 2."""
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


def _metric(request: AnalyticsRequest, snapshot: MarketSnapshot, value: object, unit: str) -> AnalyticsMetric:
    return AnalyticsMetric(
        metric_key=request.metric_key,
        value=value,
        status=AnalyticsStatus.AVAILABLE,
        unit=unit,
        as_of=snapshot.as_of,
        calculation_version=request.analytics_version,
        provenance=(AnalyticsProvenance(source="common-analytics.track2", dependencies=request.dependencies),),
    )


def _bbw(snapshot: MarketSnapshot, request: AnalyticsRequest) -> AnalyticsMetric:
    window = tuple(float(x) for x in snapshot.observations["bbw_window"])
    if not window:
        return _metric(request, snapshot, None, "ratio")
    return _metric(request, snapshot, window[-1] == min(window), "boolean")


def _volume_z(snapshot: MarketSnapshot, request: AnalyticsRequest) -> AnalyticsMetric:
    window = tuple(float(x) for x in snapshot.observations["volume_window"])
    if len(window) < 2:
        return _metric(request, snapshot, None, "zscore")
    history = window[:-1]
    mean = sum(history) / len(history)
    variance = sum((x - mean) ** 2 for x in history) / len(history)
    std = variance ** 0.5
    if std == 0:
        value = 99.0 if window[-1] > mean else 0.0
    else:
        value = (window[-1] - mean) / std
    return _metric(request, snapshot, value, "zscore")


def _obi(snapshot: MarketSnapshot, request: AnalyticsRequest) -> AnalyticsMetric:
    bids = tuple(Decimal(str(x)) for x in snapshot.observations["bid_qtys"])
    asks = tuple(Decimal(str(x)) for x in snapshot.observations["ask_qtys"])
    bid_sum = sum(bids[:5], Decimal("0"))
    ask_sum = sum(asks[:5], Decimal("0"))
    total = bid_sum + ask_sum
    value = Decimal("0") if total == 0 else (bid_sum - ask_sum) / total
    return _metric(request, snapshot, value, "ratio")


def _passthrough(observation_key: str, unit: str):
    def evaluator(snapshot: MarketSnapshot, request: AnalyticsRequest) -> AnalyticsMetric:
        return _metric(request, snapshot, snapshot.observations[observation_key], unit)
    return evaluator


def build_track2_evaluators() -> Mapping[str, object]:
    return {
        "volatility.bbw": _bbw,
        "volume.z_score": _volume_z,
        "microstructure.obi": _obi,
        "futures.basis": _passthrough("basis", "index-points"),
        "options.put_iv": _passthrough("put_iv", "decimal"),
        "options.call_iv": _passthrough("call_iv", "decimal"),
        "volume_profile.poc": _passthrough("poc_price", "index-points"),
        "volatility.active": _passthrough("active_vol", "decimal"),
        "volatility.base": _passthrough("base_vol", "decimal"),
    }


__all__ = ("build_track2_evaluators",)
