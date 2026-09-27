from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from typing import Protocol

from .track4_runtime_input_provider import Track4InputSourceUnavailable


@dataclass(frozen=True)
class Track4AttributionSnapshot:
    observed_at: datetime
    premium_spent: Decimal | None
    accumulated_gamma_profit: Decimal | None
    theta_decay_cost: Decimal | None
    source: str


class Track4AttributionProvider(Protocol):
    def snapshot(self) -> Track4AttributionSnapshot: ...

    def premium_spent(self) -> Decimal: ...

    def accumulated_gamma_profit(self) -> Decimal: ...

    def theta_decay_cost(self) -> Decimal: ...


class Track4AttributionSourceUnavailable(Track4InputSourceUnavailable):
    """Raised when the requested attribution component has no authoritative source."""
