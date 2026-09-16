from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, Sequence


@dataclass(frozen=True)
class OptionOrderBookLevel:
    price: Decimal
    quantity: Decimal


@dataclass(frozen=True)
class OptionOrderBookSnapshot:
    symbol: str
    observed_hour: str
    ask_levels: Sequence[OptionOrderBookLevel]
    bid_levels: Sequence[OptionOrderBookLevel]
    source: str

    @property
    def ask_quantities(self) -> tuple[Decimal, ...]:
        return tuple(level.quantity for level in self.ask_levels)

    @property
    def bid_quantities(self) -> tuple[Decimal, ...]:
        return tuple(level.quantity for level in self.bid_levels)

    def is_complete(self, depth: int = 5) -> bool:
        return (
            bool(self.symbol)
            and len(self.ask_levels) >= depth
            and len(self.bid_levels) >= depth
            and all(level.quantity >= 0 for level in self.ask_levels[:depth])
            and all(level.quantity >= 0 for level in self.bid_levels[:depth])
        )


class OptionOrderBookSource(Protocol):
    def get_order_book(self, symbol: str) -> OptionOrderBookSnapshot | None: ...


class UnavailableOptionOrderBookSource:
    """Explicit unavailable boundary; never fabricates order-book quantities."""

    def get_order_book(self, symbol: str) -> OptionOrderBookSnapshot | None:
        return None
