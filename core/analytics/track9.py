"""Common Analytics evaluators for Strategy 9 event insurance."""
from __future__ import annotations

from decimal import Decimal
from typing import Mapping

from contracts.analytics import (
    AnalyticsMetric,
    AnalyticsProvenance,
    AnalyticsRequest,
    AnalyticsStatus,
)


def _metric(request, snapshot, value, unit):
    return AnalyticsMetric(
        request.metric_key,
        value,
        AnalyticsStatus.AVAILABLE,
        unit,
        snapshot.as_of,
        request.analytics_version,
        (AnalyticsProvenance(
            source="common-analytics.track9",
            dependencies=request.dependencies,
            source_as_of=snapshot.as_of,
        ),),
    )


def _unavailable(request, snapshot, unit):
    return AnalyticsMetric(
        request.metric_key,
        None,
        AnalyticsStatus.UNAVAILABLE,
        unit,
        snapshot.as_of,
        request.analytics_version,
        (AnalyticsProvenance(
            source="common-analytics.track9",
            dependencies=request.dependencies,
            source_as_of=snapshot.as_of,
        ),),
    )


def _passthrough(observation, unit):
    def evaluate(snapshot, request):
        value = snapshot.observations.get(observation)
        if value is None:
            return _unavailable(request, snapshot, unit)
        return _metric(request, snapshot, value, unit)
    return evaluate


def _net_pnl(snapshot, request):
    pnl = snapshot.observations.get("current_pnl")
    fees = snapshot.observations.get("total_fees")
    if pnl is None or fees is None:
        return _unavailable(request, snapshot, "currency")
    return _metric(request, snapshot, Decimal(str(pnl)) - Decimal(str(fees)), "currency")


def build_track9_evaluators() -> Mapping[str, object]:
    return {
        "portfolio.active_sell_qty": _passthrough("active_sell_qty", "contracts"),
        "portfolio.insurance_qty": _passthrough("insurance_qty", "contracts"),
        "events.upcoming": _passthrough("event_upcoming", "bool"),
        "options.iv_spike": _passthrough("iv_spike", "percentage-points"),
        "options.iv_crush": _passthrough("iv_crush", "percentage-points"),
        "portfolio.current_pnl": _passthrough("current_pnl", "currency"),
        "portfolio.total_fees": _passthrough("total_fees", "currency"),
        "portfolio.net_pnl": _net_pnl,
        "portfolio.margin_ratio": _passthrough("margin_ratio", "ratio"),
        "risk.guard_active": _passthrough("risk_guard_active", "bool"),
        "portfolio.event_budget": _passthrough("event_budget", "currency"),
        "portfolio.estimated_event_cost": _passthrough("estimated_event_cost", "currency"),
        "options.atm_call_strike": _passthrough("atm_call_strike", "index-points"),
        "options.atm_put_strike": _passthrough("atm_put_strike", "index-points"),
        "options.contract_multiplier": _passthrough("contract_multiplier", "contract-unit"),
        "portfolio.premium_spent": _passthrough("premium_spent", "currency"),
    }


__all__ = ("build_track9_evaluators",)
