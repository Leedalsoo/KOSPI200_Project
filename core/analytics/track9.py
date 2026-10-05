"""Common Analytics evaluators for Strategy 9 event insurance."""
from __future__ import annotations

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


def build_track9_evaluators() -> Mapping[str, object]:
    return {
        "price.last": _passthrough("current_price", "index-points"),
        "options.atm_call_strike": _passthrough("atm_call_strike", "index-points"),
        "options.atm_put_strike": _passthrough("atm_put_strike", "index-points"),
        "options.contract_multiplier": _passthrough("contract_multiplier", "contract-unit"),
        "options.track9_put_entry_price": _passthrough("track9_put_entry_price", "option-price"),
        "options.track9_call_entry_price": _passthrough("track9_call_entry_price", "option-price"),
        "options.track9_put_mark_price": _passthrough("track9_put_mark_price", "option-price"),
        "options.track9_call_mark_price": _passthrough("track9_call_mark_price", "option-price"),
        # Legacy event/IV evaluators are intentionally retained as non-required
        # compatibility metrics; Strategy9 no longer declares or consumes them.
        "portfolio.active_sell_qty": _passthrough("active_sell_qty", "contracts"),
        "portfolio.insurance_qty": _passthrough("insurance_qty", "contracts"),
        "events.upcoming": _passthrough("event_upcoming", "bool"),
        "options.iv_spike": _passthrough("iv_spike", "percentage-points"),
        "options.iv_crush": _passthrough("iv_crush", "percentage-points"),
        "portfolio.event_budget": _passthrough("event_budget", "currency"),
        "portfolio.estimated_event_cost": _passthrough("estimated_event_cost", "currency"),
        "portfolio.premium_spent": _passthrough("premium_spent", "currency"),
    }


__all__ = ("build_track9_evaluators",)
