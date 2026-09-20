"""Common Analytics evaluators required by Strategy 4."""
from __future__ import annotations

from decimal import Decimal
from typing import Mapping

from contracts.analytics import AnalyticsMetric, AnalyticsProvenance, AnalyticsRequest, AnalyticsStatus, MarketSnapshot


def _metric(request: AnalyticsRequest, snapshot: MarketSnapshot, value: object, unit: str) -> AnalyticsMetric:
    return AnalyticsMetric(request.metric_key, value, AnalyticsStatus.AVAILABLE, unit, snapshot.as_of, request.analytics_version, (AnalyticsProvenance(source="common-analytics.track4", dependencies=request.dependencies, source_as_of=snapshot.as_of),))


def _unavailable(request: AnalyticsRequest, snapshot: MarketSnapshot, unit: str) -> AnalyticsMetric:
    return AnalyticsMetric(request.metric_key, None, AnalyticsStatus.UNAVAILABLE, unit, snapshot.as_of, request.analytics_version, (AnalyticsProvenance(source="common-analytics.track4", dependencies=request.dependencies, source_as_of=snapshot.as_of),))


def _passthrough(observation: str, unit: str):
    def evaluator(snapshot: MarketSnapshot, request: AnalyticsRequest) -> AnalyticsMetric:
        value = snapshot.observations[observation]
        return _unavailable(request, snapshot, unit) if value is None else _metric(request, snapshot, value, unit)
    return evaluator


def _volatility_ratio(snapshot: MarketSnapshot, request: AnalyticsRequest) -> AnalyticsMetric:
    active = Decimal(str(snapshot.observations["active_vol"]))
    base = Decimal(str(snapshot.observations["base_vol"]))
    if active <= 0 or base <= 0:
        return _unavailable(request, snapshot, "ratio")
    return _metric(request, snapshot, active / base, "ratio")


def _tick_deadband(snapshot: MarketSnapshot, request: AnalyticsRequest) -> AnalyticsMetric:
    history = tuple(Decimal(str(value)) for value in snapshot.observations["price_history"])
    if not history:
        return _unavailable(request, snapshot, "ratio")
    last = history[-1]
    if last == 0 or len(history) < 2:
        movement = Decimal("0")
    else:
        movements = tuple(abs(history[i] - history[i - 1]) for i in range(1, len(history)))
        movement = sum(movements, Decimal("0")) / Decimal(len(movements))
    normalized = Decimal("0") if last == 0 else movement / last
    return _metric(request, snapshot, max(Decimal("0.2"), min(normalized * Decimal("5.0"), Decimal("0.6"))), "ratio")


def build_track4_evaluators() -> Mapping[str, object]:
    return {
        "volatility.active": _passthrough("active_vol", "decimal"),
        "volatility.base": _passthrough("base_vol", "decimal"),
        "volatility.ratio": _volatility_ratio,
        "options.delta": _passthrough("current_delta", "delta"),
        "options.gamma": _passthrough("current_gamma", "gamma"),
        "options.theta": _passthrough("current_theta", "theta"),
        "portfolio.current_pnl": _passthrough("current_pnl", "currency"),
        "portfolio.equity": _passthrough("current_equity", "currency"),
        "portfolio.premium_spent": _passthrough("premium_spent", "currency"),
        "price.tick_deadband": _tick_deadband,
    }


__all__ = ("build_track4_evaluators",)
