from __future__ import annotations

from decimal import Decimal
from typing import Protocol, Sequence


class Track4MarketHistoryProjection(Protocol):
    """Read-only projection of observed market price history."""

    def price_history(self) -> Sequence[Decimal]: ...
