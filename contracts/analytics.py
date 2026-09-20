from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Sequence

from contracts.types import CanonicalMarketTick, OptionInstrumentIdentity


class AnalyticsStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class AnalyticsProvenance:
    source: str
    dependencies: tuple[str, ...] = ()
    source_as_of: datetime | None = None
    model_version: str | None = None

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError("analytics provenance source is required")
        object.__setattr__(self, "dependencies", tuple(self.dependencies))


@dataclass(frozen=True)
class MarketSnapshot:
    run_id: str
    as_of: datetime
    provenance: AnalyticsProvenance
    instrument_identity: OptionInstrumentIdentity | None
    observations: Mapping[str, object]
    session_metadata: Mapping[str, object] = MappingProxyType({})

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id is required")
        object.__setattr__(self, "observations", MappingProxyType(dict(self.observations)))
        object.__setattr__(self, "session_metadata", MappingProxyType(dict(self.session_metadata)))

    @property
    def ticks(self) -> Mapping[str, CanonicalMarketTick]:
        return MappingProxyType({
            key: value for key, value in self.observations.items()
            if isinstance(value, CanonicalMarketTick)
        })


@dataclass(frozen=True)
class AnalyticsRequest:
    metric_key: str
    timeframe: str
    window: int
    dependencies: tuple[str, ...]
    freshness_seconds: float | None
    source_requirement: str | None
    analytics_version: str

    def __post_init__(self) -> None:
        if not self.metric_key or any(part == "" for part in self.metric_key.split(".")):
            raise ValueError("metric_key must be a stable non-empty dotted key")
        if not self.timeframe:
            raise ValueError("timeframe is required")
        if self.window <= 0:
            raise ValueError("window must be positive")
        if self.freshness_seconds is not None and self.freshness_seconds < 0:
            raise ValueError("freshness_seconds must be non-negative")
        if not self.analytics_version:
            raise ValueError("analytics_version is required")
        object.__setattr__(self, "dependencies", tuple(self.dependencies))


@dataclass(frozen=True)
class AnalyticsMetric:
    metric_key: str
    value: object | None
    status: AnalyticsStatus | str
    unit: str
    as_of: datetime
    calculation_version: str
    provenance: tuple[AnalyticsProvenance | str, ...]

    def __post_init__(self) -> None:
        if not self.metric_key or any(part == "" for part in self.metric_key.split(".")):
            raise ValueError("metric_key must be a stable non-empty dotted key")
        if not self.unit:
            raise ValueError("unit is required")
        if not self.calculation_version:
            raise ValueError("calculation_version is required")
        status = AnalyticsStatus(self.status)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "provenance", tuple(self.provenance))


@dataclass(frozen=True)
class AnalyticsSnapshot:
    run_id: str
    instrument_identity: OptionInstrumentIdentity | None
    as_of: datetime
    timeframe: str
    window: int
    analytics_version: str
    metrics: Mapping[str, AnalyticsMetric]

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id is required")
        if not self.timeframe:
            raise ValueError("timeframe is required")
        if self.window <= 0:
            raise ValueError("window must be positive")
        if not self.analytics_version:
            raise ValueError("analytics_version is required")
        normalized = dict(self.metrics)
        for key, metric in normalized.items():
            if key != metric.metric_key:
                raise ValueError("metric mapping key must match metric_key")
        object.__setattr__(self, "metrics", MappingProxyType(normalized))

    def get(self, metric_key: str) -> AnalyticsMetric | None:
        return self.metrics.get(metric_key)


__all__: Sequence[str] = (
    "AnalyticsMetric",
    "AnalyticsProvenance",
    "AnalyticsRequest",
    "AnalyticsSnapshot",
    "AnalyticsStatus",
    "MarketSnapshot",
)
