from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Mapping, Protocol, Sequence, runtime_checkable

from contracts.analytics import AnalyticsMetric, AnalyticsSnapshot, AnalyticsStatus
from contracts.types import OptionInstrumentIdentity
from core.domain.market_models import MarketState


@dataclass(frozen=True)
class CommonStrategyInput:
    """Only values whose meaning and unit are shared by multiple strategies."""
    as_of: datetime
    current_price: Decimal | None = None
    active_vol: Decimal | None = None
    base_vol: Decimal | None = None
    budget: Decimal | None = None
    current_pnl: Decimal | None = None
    total_fees: Decimal | None = None
    time_str: str | None = None
    date_str: str | None = None


class StrategyPayload(Protocol):
    """Marker contract for strategy-specific typed input payloads."""


@dataclass(frozen=True)
class UnavailableStrategyPayload:
    """Explicit fail-closed payload when authoritative Runtime data is absent."""
    strategy_id: str
    required_sources: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class StrategyInput:
    common: CommonStrategyInput | None = None
    payload: StrategyPayload | None = None
    data_status: Mapping[str, str] | None = None


@dataclass(frozen=True)
class StrategyContext:
    market_state: MarketState | None = None
    strategy_id: str = ""
    input: StrategyInput | None = None
    analytics: AnalyticsSnapshot | None = None


@dataclass(frozen=True)
class Signal:
    strategy_id: str
    direction: str
    confidence: float
    reason: str
    instrument_identity: OptionInstrumentIdentity | None = None
    option_type_override: str | None = None
    strike_override: Decimal | None = None
    execution_proposal: "StrategyExecutionProposal | None" = None


@dataclass(frozen=True)
class StrategyFeatureRequirement:
    """Declared analytics dependency of a strategy plug-in."""

    metric_key: str
    timeframe: str
    freshness_seconds: float | None
    allowed_statuses: frozenset[AnalyticsStatus]

    def __post_init__(self) -> None:
        if not self.metric_key or any(part == "" for part in self.metric_key.split(".")):
            raise ValueError("metric_key must be a stable non-empty dotted key")
        if not self.timeframe:
            raise ValueError("timeframe is required")
        if self.freshness_seconds is not None and self.freshness_seconds < 0:
            raise ValueError("freshness_seconds must be non-negative")
        if not self.allowed_statuses:
            raise ValueError("allowed_statuses must not be empty")
        object.__setattr__(self, "allowed_statuses", frozenset(AnalyticsStatus(status) for status in self.allowed_statuses))


@runtime_checkable
class StrategyPlugin(Protocol):
    strategy_id: str
    version: str

    def feature_requirements(self) -> Sequence[StrategyFeatureRequirement]: ...
    def initialize(self, context: StrategyContext) -> None: ...
    def on_market_state(self, context: StrategyContext) -> None: ...
    def evaluate(self, context: StrategyContext) -> Sequence[Signal]: ...
    def reset(self) -> None: ...


def _unavailable_metric(requirement: StrategyFeatureRequirement, snapshot: AnalyticsSnapshot) -> AnalyticsMetric:
    return AnalyticsMetric(
        metric_key=requirement.metric_key,
        value=None,
        status=AnalyticsStatus.UNAVAILABLE,
        unit="UNSPECIFIED",
        as_of=snapshot.as_of,
        calculation_version=snapshot.analytics_version,
        provenance=("strategy-plugin-contract",),
    )


def validate_strategy_features(
    requirements: Sequence[StrategyFeatureRequirement],
    snapshot: AnalyticsSnapshot,
) -> tuple[AnalyticsMetric, ...]:
    """Return canonical metrics only when each declared requirement is usable."""
    results: list[AnalyticsMetric] = []
    for requirement in requirements:
        metric = snapshot.get(requirement.metric_key)
        if metric is None:
            results.append(_unavailable_metric(requirement, snapshot))
            continue
        if snapshot.timeframe != requirement.timeframe:
            results.append(AnalyticsMetric(
                metric_key=metric.metric_key,
                value=None,
                status=AnalyticsStatus.BLOCKED,
                unit=metric.unit,
                as_of=metric.as_of,
                calculation_version=metric.calculation_version,
                provenance=metric.provenance,
            ))
            continue
        if metric.status not in requirement.allowed_statuses:
            results.append(AnalyticsMetric(
                metric_key=metric.metric_key,
                value=None,
                status=metric.status,
                unit=metric.unit,
                as_of=metric.as_of,
                calculation_version=metric.calculation_version,
                provenance=metric.provenance,
            ))
            continue
        if requirement.freshness_seconds is not None:
            age = (snapshot.as_of - metric.as_of).total_seconds()
            if age > requirement.freshness_seconds:
                results.append(AnalyticsMetric(
                    metric_key=metric.metric_key,
                    value=None,
                    status=AnalyticsStatus.STALE,
                    unit=metric.unit,
                    as_of=metric.as_of,
                    calculation_version=metric.calculation_version,
                    provenance=metric.provenance,
                ))
                continue
        results.append(metric)
    return tuple(results)


class Strategy(Protocol):
    strategy_id: str
    version: str
    def initialize(self, context: StrategyContext) -> None: ...
    def on_market_state(self, context: StrategyContext) -> None: ...
    def evaluate(self, context: StrategyContext) -> Sequence[Signal]: ...
    def reset(self) -> None: ...
