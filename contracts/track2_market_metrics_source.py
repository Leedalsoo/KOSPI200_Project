from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, Sequence


@dataclass(frozen=True)
class Track2MarketMetrics:
    bbw_window: tuple[Decimal, ...]
    volume_window: tuple[Decimal, ...]
    active_vol: Decimal
    base_vol: Decimal


class Track2MarketMetricsSource(Protocol):
    def get_metrics(self, symbol: str) -> Track2MarketMetrics | None: ...


class UnavailableTrack2MarketMetricsSource:
    def get_metrics(self, symbol: str) -> Track2MarketMetrics | None:
        return None
