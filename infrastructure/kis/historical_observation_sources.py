from __future__ import annotations
from bisect import bisect_right
from datetime import datetime
from decimal import Decimal
from typing import Sequence
from contracts.option_orderbook_source import OptionOrderBookSnapshot, OptionOrderBookLevel
from contracts.track2_option_iv_source import Track2OptionIVSource
from contracts.types import MarketObservation

class HistoricalObservationOptionSource(Track2OptionIVSource):
    """Replay-time option IV/order-book source backed only by historical observations."""
    def __init__(self, observations: Sequence[MarketObservation]) -> None:
        self._as_of: datetime | None = None
        self._iv: dict[tuple[str, str, Decimal], list[tuple[datetime, Decimal]]] = {}
        self._books: dict[str, list[tuple[datetime, OptionOrderBookSnapshot]]] = {}
        for observation in observations:
            observed_at = observation.observed_at or observation.collected_at
            if observed_at is None:
                continue
            identity = observation.contract
            key = (str(identity.expiry).replace("-", "")[:8], str(identity.option_type).upper(), Decimal(str(identity.strike)))
            iv = getattr(observation.analytics, "implied_volatility", None)
            if iv is not None:
                self._iv.setdefault(key, []).append((observed_at, Decimal(str(iv))))
            book = observation.order_book
            if book is not None and len(book.bids) >= 5 and len(book.asks) >= 5:
                snapshot = OptionOrderBookSnapshot(
                    symbol=str(identity.symbol),
                    observed_hour=observed_at.strftime("%H%M%S%f").rstrip("0"),
                    ask_levels=tuple(OptionOrderBookLevel(price=Decimal(str(level.price)), quantity=Decimal(str(level.quantity))) for level in book.asks[:5]),
                    bid_levels=tuple(OptionOrderBookLevel(price=Decimal(str(level.price)), quantity=Decimal(str(level.quantity))) for level in book.bids[:5]),
                    source=f"HistoricalObservationStore:{observation.source}",
                )
                self._books.setdefault(str(identity.symbol), []).append((observed_at, snapshot))
        for values in self._iv.values():
            values.sort(key=lambda item: item[0])
        for values in self._books.values():
            values.sort(key=lambda item: item[0])

    def set_as_of(self, observed_at: datetime) -> None:
        self._as_of = observed_at

    def _latest(self, values):
        if self._as_of is None or not values:
            return None
        index = bisect_right([item[0] for item in values], self._as_of) - 1
        return values[index][1] if index >= 0 else None

    def get_iv(self, *, expiry: str, option_type: str, strike: Decimal) -> Decimal | None:
        key = (str(expiry).replace("-", "")[:8], str(option_type).upper(), Decimal(str(strike)))
        return self._latest(self._iv.get(key, ()))

    def get_order_book(self, symbol: str) -> OptionOrderBookSnapshot | None:
        return self._latest(self._books.get(str(symbol).strip(), ()))
