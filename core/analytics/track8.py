"""Common Analytics evaluators for Strategy 8 monthly strangle."""
from __future__ import annotations
from decimal import Decimal
from typing import Mapping
from contracts.analytics import AnalyticsMetric, AnalyticsProvenance, AnalyticsRequest, AnalyticsStatus


def _metric(request, snapshot, value, unit):
    return AnalyticsMetric(request.metric_key, value, AnalyticsStatus.AVAILABLE, unit, snapshot.as_of,
                           request.analytics_version,
                           (AnalyticsProvenance(source="common-analytics.track8", dependencies=request.dependencies, source_as_of=snapshot.as_of),))


def _unavailable(request, snapshot, unit):
    return AnalyticsMetric(request.metric_key, None, AnalyticsStatus.UNAVAILABLE, unit, snapshot.as_of,
                           request.analytics_version,
                           (AnalyticsProvenance(source="common-analytics.track8", dependencies=request.dependencies, source_as_of=snapshot.as_of),))


def _passthrough(observation, unit):
    def evaluate(snapshot, request):
        value = snapshot.observations.get(observation)
        return _unavailable(request, snapshot, unit) if value is None else _metric(request, snapshot, value, unit)
    return evaluate


def _net_pnl(snapshot, request):
    pnl = snapshot.observations.get("current_pnl")
    fees = snapshot.observations.get("total_fees")
    if pnl is None or fees is None:
        return _unavailable(request, snapshot, "currency")
    return _metric(request, snapshot, Decimal(str(pnl)) - Decimal(str(fees)), "currency")


def _moneyness(snapshot, request):
    price = snapshot.observations.get("current_price")
    call = snapshot.observations.get("call_strike")
    put = snapshot.observations.get("put_strike")
    if price is None or call is None or put is None:
        return _unavailable(request, snapshot, "ratio")
    return _metric(request, snapshot, {
        "call_distance": Decimal(str(price)) - Decimal(str(call)),
        "put_distance": Decimal(str(put)) - Decimal(str(price)),
    }, "index-points")


def build_track8_evaluators() -> Mapping[str, object]:
    return {
        "options.dte": _passthrough("dte", "days"),
        "options.call_iv": _passthrough("call_iv", "iv-points"),
        "options.put_iv": _passthrough("put_iv", "iv-points"),
        "options.atm_iv": _passthrough("atm_iv", "iv-points"),
        "options.call_strike": _passthrough("call_strike", "index-points"),
        "options.put_strike": _passthrough("put_strike", "index-points"),
        "options.call_contract_multiplier": _passthrough("call_contract_multiplier", "contract-unit"),
        "options.put_contract_multiplier": _passthrough("put_contract_multiplier", "contract-unit"),
        "options.moneyness": _moneyness,
        "market.current_regime": _passthrough("current_regime", "regime"),
        "volatility.active": _passthrough("active_vol", "volatility"),
        "portfolio.current_pnl": _passthrough("current_pnl", "currency"),
        "portfolio.total_fees": _passthrough("total_fees", "currency"),
        "portfolio.net_pnl": _net_pnl,
        "portfolio.margin_ratio": _passthrough("margin_ratio", "ratio"),
        "risk.guard_active": _passthrough("risk_guard_active", "bool"),
    }


__all__ = ("build_track8_evaluators",)
