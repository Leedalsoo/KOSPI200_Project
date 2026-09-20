from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from contracts.analytics import (
    AnalyticsMetric,
    AnalyticsProvenance,
    AnalyticsRequest,
    AnalyticsSnapshot,
    AnalyticsStatus,
    MarketSnapshot,
)

AnalyticsEvaluator = Callable[[MarketSnapshot, AnalyticsRequest], AnalyticsMetric]


@dataclass(frozen=True)
class _EvaluationKey:
    metric_key: str
    timeframe: str
    window: int
    analytics_version: str


class AnalyticsEngine:
    """Single-cycle, dependency-aware evaluator for canonical analytics."""

    def __init__(self, evaluators: Mapping[str, AnalyticsEvaluator]) -> None:
        self._evaluators = dict(evaluators)

    def evaluate(
        self,
        market_snapshot: MarketSnapshot,
        requests: Sequence[AnalyticsRequest],
    ) -> AnalyticsSnapshot:
        if not requests:
            raise ValueError("at least one analytics request is required")

        first = requests[0]
        if any(
            (request.timeframe, request.window, request.analytics_version)
            != (first.timeframe, first.window, first.analytics_version)
            for request in requests
        ):
            raise ValueError("one AnalyticsSnapshot requires one timeframe/window/version")

        cache: dict[_EvaluationKey, AnalyticsMetric] = {}
        metrics: dict[str, AnalyticsMetric] = {}
        for request in requests:
            key = _EvaluationKey(
                request.metric_key,
                request.timeframe,
                request.window,
                request.analytics_version,
            )
            metric = cache.get(key)
            if metric is None:
                metric = self._evaluate_one(market_snapshot, request)
                cache[key] = metric
            metrics.setdefault(request.metric_key, metric)

        return AnalyticsSnapshot(
            run_id=market_snapshot.run_id,
            instrument_identity=market_snapshot.instrument_identity,
            as_of=market_snapshot.as_of,
            timeframe=first.timeframe,
            window=first.window,
            analytics_version=first.analytics_version,
            metrics=metrics,
        )

    def _evaluate_one(
        self,
        market_snapshot: MarketSnapshot,
        request: AnalyticsRequest,
    ) -> AnalyticsMetric:
        missing = tuple(
            dependency
            for dependency in request.dependencies
            if dependency not in market_snapshot.observations
        )
        if missing:
            return AnalyticsMetric(
                metric_key=request.metric_key,
                value=None,
                status=AnalyticsStatus.UNAVAILABLE,
                unit="UNSPECIFIED",
                as_of=market_snapshot.as_of,
                calculation_version=request.analytics_version,
                provenance=(
                    AnalyticsProvenance(
                        source="analytics-engine",
                        dependencies=missing,
                        source_as_of=market_snapshot.as_of,
                    ),
                ),
            )

        evaluator = self._evaluators.get(request.metric_key)
        if evaluator is None:
            return AnalyticsMetric(
                metric_key=request.metric_key,
                value=None,
                status=AnalyticsStatus.UNAVAILABLE,
                unit="UNSPECIFIED",
                as_of=market_snapshot.as_of,
                calculation_version=request.analytics_version,
                provenance=(
                    AnalyticsProvenance(
                        source="analytics-engine",
                        dependencies=request.dependencies,
                        source_as_of=market_snapshot.as_of,
                    ),
                ),
            )
        return evaluator(market_snapshot, request)


__all__ = ("AnalyticsEngine", "AnalyticsEvaluator")
