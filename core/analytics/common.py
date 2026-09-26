"""Canonical common analytics contracts and evaluators shared by strategies."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Mapping, Sequence

from contracts.analytics import (
    AnalyticsMetric,
    AnalyticsProvenance,
    AnalyticsRequest,
    AnalyticsSnapshot,
    AnalyticsStatus,
    MarketSnapshot,
)


@dataclass(frozen=True)
class CanonicalMetricContract:
    metric_key: str
    canonical_unit: str
    source_observation: tuple[str, ...]
    dependencies: tuple[str, ...]
    timeframe: str = "tick"
    window: int = 1
    freshness_seconds: float | None = 1.0
    authoritative_source_required: bool = True
    calculation_version: str = "1"


_COMMON = (
    ("price.last", "index-points", ("current_price",), ("current_price",)),
    ("volatility.active", "decimal", ("active_vol",), ("active_vol",)),
    ("volatility.base", "decimal", ("base_vol",), ("base_vol",)),
    ("volatility.ratio", "ratio", ("active_vol", "base_vol"), ("active_vol", "base_vol")),
    ("options.call_iv", "iv-points", ("call_iv",), ("call_iv",)),
    ("options.put_iv", "iv-points", ("put_iv",), ("put_iv",)),
    ("portfolio.total_fees", "currency", ("total_fees",), ("total_fees",)),
    ("portfolio.margin_ratio", "ratio", ("margin_ratio",), ("margin_ratio",)),
    ("portfolio.current_pnl", "currency", ("current_pnl",), ("current_pnl",)),
    ("portfolio.net_pnl", "currency", ("current_pnl", "total_fees"), ("current_pnl", "total_fees")),
)

COMMON_METRIC_CONTRACTS = {
    key: CanonicalMetricContract(key, unit, source, deps)
    for key, unit, source, deps in _COMMON
}
def build_common_requests(metric_keys: Sequence[str]) -> tuple[AnalyticsRequest, ...]:
    """Build a deterministic, deduplicated union of strategy metric requests."""
    requests: list[AnalyticsRequest] = []
    seen: set[str] = set()
    for metric_key in metric_keys:
        if metric_key in seen:
            continue
        contract = COMMON_METRIC_CONTRACTS.get(metric_key)
        if contract is None:
            continue
        seen.add(metric_key)
        requests.append(AnalyticsRequest(
            metric_key=contract.metric_key,
            timeframe=contract.timeframe,
            window=contract.window,
            dependencies=contract.dependencies,
            freshness_seconds=contract.freshness_seconds,
            source_requirement="authoritative" if contract.authoritative_source_required else None,
            analytics_version=contract.calculation_version,
        ))
    if not requests:
        raise ValueError("at least one canonical common metric is required")
    return tuple(requests)


def _metric(request, snapshot, value, unit, *, available=True):
    status = AnalyticsStatus.AVAILABLE if available and value is not None else AnalyticsStatus.UNAVAILABLE
    return AnalyticsMetric(
        request.metric_key, value if status is AnalyticsStatus.AVAILABLE else None,
        status, unit, snapshot.as_of, request.analytics_version,
        (AnalyticsProvenance(
            source="common-analytics.canonical",
            dependencies=request.dependencies,
            source_as_of=snapshot.as_of,
        ),),
    )


def _passthrough(observation: str, unit: str):
    def evaluate(snapshot, request):
        return _metric(request, snapshot, snapshot.observations.get(observation), unit)
    return evaluate


def _ratio(snapshot, request):
    active = snapshot.observations.get("active_vol")
    base = snapshot.observations.get("base_vol")
    if active is None or base is None:
        return _metric(request, snapshot, None, "ratio", available=False)
    active_value, base_value = Decimal(str(active)), Decimal(str(base))
    if active_value < 0 or base_value <= 0:
        return _metric(request, snapshot, None, "ratio", available=False)
    return _metric(request, snapshot, active_value / base_value, "ratio")


def _net_pnl(snapshot, request):
    current_pnl = snapshot.observations.get("current_pnl")
    total_fees = snapshot.observations.get("total_fees")
    if current_pnl is None or total_fees is None:
        return _metric(request, snapshot, None, "currency", available=False)
    return _metric(
        request,
        snapshot,
        Decimal(str(current_pnl)) - Decimal(str(total_fees)),
        "currency",
    )


_EVALUATORS: Mapping[str, Callable] = {
    "price.last": _passthrough("current_price", "index-points"),
    "volatility.active": _passthrough("active_vol", "decimal"),
    "volatility.base": _passthrough("base_vol", "decimal"),
    "volatility.ratio": _ratio,
    "options.call_iv": _passthrough("call_iv", "iv-points"),
    "options.put_iv": _passthrough("put_iv", "iv-points"),
    "portfolio.total_fees": _passthrough("total_fees", "currency"),
    "portfolio.margin_ratio": _passthrough("margin_ratio", "ratio"),
    "portfolio.current_pnl": _passthrough("current_pnl", "currency"),
    "portfolio.net_pnl": _net_pnl,
}


def merge_analytics_snapshots(
    common_snapshot: AnalyticsSnapshot,
    strategy_snapshot: AnalyticsSnapshot,
) -> AnalyticsSnapshot:
    """Merge one shared common snapshot with strategy-only metrics safely."""
    if (
        common_snapshot.run_id != strategy_snapshot.run_id
        or common_snapshot.as_of != strategy_snapshot.as_of
        or common_snapshot.timeframe != strategy_snapshot.timeframe
        or common_snapshot.window != strategy_snapshot.window
        or common_snapshot.analytics_version != strategy_snapshot.analytics_version
    ):
        raise ValueError("incompatible AnalyticsSnapshot contract boundaries")
    overlap = set(common_snapshot.metrics).intersection(strategy_snapshot.metrics)
    if overlap:
        raise ValueError(f"common/strategy metric overlap: {sorted(overlap)}")
    return AnalyticsSnapshot(
        run_id=common_snapshot.run_id,
        instrument_identity=common_snapshot.instrument_identity,
        as_of=common_snapshot.as_of,
        timeframe=common_snapshot.timeframe,
        window=common_snapshot.window,
        analytics_version=common_snapshot.analytics_version,
        metrics={**common_snapshot.metrics, **strategy_snapshot.metrics},
    )


def build_common_analytics_snapshot(
    market_snapshot: MarketSnapshot,
    metric_keys: Sequence[str],
) -> AnalyticsSnapshot:
    """Evaluate one canonical request-set against one market snapshot."""
    requests = build_common_requests(metric_keys)
    evaluators = {key: _EVALUATORS[key] for key in (r.metric_key for r in requests)}
    from core.analytics.engine import AnalyticsEngine
    return AnalyticsEngine(evaluators).evaluate(market_snapshot, requests)


__all__ = (
    "CanonicalMetricContract",
    "COMMON_METRIC_CONTRACTS",
    "build_common_requests",
    "build_common_analytics_snapshot",
    "merge_analytics_snapshots",
)
