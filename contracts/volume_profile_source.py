from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class VolumeProfilePoint:
    price: Decimal
    volume: Decimal
    observed_hour: str
    source: str


class VolumeProfileSource(Protocol):
    def get_poc(self, symbol: str) -> Decimal | None: ...


class UnavailableVolumeProfileSource:
    """Explicit unavailable boundary; never fabricates a POC."""

    def get_poc(self, symbol: str) -> Decimal | None:
        return None
