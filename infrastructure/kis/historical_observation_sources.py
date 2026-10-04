from __future__ import annotations
from bisect import bisect_right
from datetime import datetime
from decimal import Decimal
from typing import Sequence
from contracts.option_orderbook_source import OptionOrderBookSnapshot, OptionOrderBookLevel
from contracts.track2_option_iv_source import Track2OptionIVSource
from contracts.types import MarketObservation

class HistoricalObservationOptionSource(Track2OptionIVSource):
    """Replay-time option IV/order-book/Greeks source backed only by historical observations."""
    def __init__(self, observations: Sequence[MarketObservation]) -> None:
        self._as_of: datetime | None = None
        self._iv: dict[tuple[str, str, Decimal], list[tuple[datetime, Decimal]]] = {}
        self._iv_source: dict[tuple[str, str, Decimal], list[tuple[datetime, str]]] = {}
        self._delta: dict[tuple[str, str, Decimal], list[tuple[datetime, Decimal]]] = {}
        self._delta_by_instrument: dict[str, list[tuple[datetime, Decimal]]] = {}
        self._books: dict[str, list[tuple[datetime, OptionOrderBookSnapshot]]] = {}
        self._iv_times: dict[tuple[str, str, Decimal], list[datetime]] = {}
        self._iv_source_times: dict[tuple[str, str, Decimal], list[datetime]] = {}
        self._delta_times: dict[tuple[str, str, Decimal], list[datetime]] = {}
        self._delta_by_instrument_times: dict[str, list[datetime]] = {}
        self._book_times: dict[str, list[datetime]] = {}
        for observation in observations:
            observed_at = observation.observed_at or observation.collected_at
            if observed_at is None:
                continue
            identity = observation.contract
            key = (str(identity.expiry).replace("-", "")[:8], str(identity.option_type).upper(), Decimal(str(identity.strike)))
            iv = getattr(observation.analytics, "implied_volatility", None)
            if iv is not None:
                self._iv.setdefault(key, []).append((observed_at, Decimal(str(iv))))
                self._iv_source.setdefault(key, []).append((observed_at, str(observation.source)))
            delta = getattr(observation.analytics, "delta", None)
            if delta is not None:
                delta_value = Decimal(str(delta))
                self._delta.setdefault(key, []).append((observed_at, delta_value))
                self._delta_by_instrument.setdefault(str(identity.instrument_id), []).append((observed_at, delta_value))
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
        for values in self._delta.values():
            values.sort(key=lambda item: item[0])
        for values in self._delta_by_instrument.values():
            values.sort(key=lambda item: item[0])
        for values in self._books.values():
            values.sort(key=lambda item: item[0])
        self._iv_times = {key: [item[0] for item in values] for key, values in self._iv.items()}
        self._iv_source_times = {key: [item[0] for item in values] for key, values in self._iv_source.items()}
        self._delta_times = {key: [item[0] for item in values] for key, values in self._delta.items()}
        self._delta_by_instrument_times = {
            key: [item[0] for item in values] for key, values in self._delta_by_instrument.items()
        }
        self._book_times = {key: [item[0] for item in values] for key, values in self._books.items()}

    def set_as_of(self, observed_at: datetime) -> None:
        self._as_of = observed_at

    @staticmethod
    def _latest(values, timestamps, as_of: datetime | None):
        if as_of is None or not values:
            return None
        index = bisect_right(timestamps, as_of) - 1
        return values[index][1] if index >= 0 else None

    def get_iv_source(self, *, expiry: str, option_type: str, strike: Decimal):
        normalized_expiry = str(expiry).replace("-", "")
        option_type = str(option_type).upper()
        strike = Decimal(str(strike))
        key = (normalized_expiry[:8], option_type, strike)
        values = self._iv.get(key, ())
        if not values and len(normalized_expiry) >= 6:
            month = normalized_expiry[:6]
            candidates = [v for k, v in self._iv.items()
                          if k[0].startswith(month) and k[1] == option_type and k[2] == strike]
            if len(candidates) == 1:
                values = candidates[0]
        if self._as_of is None or not values:
            return None
        source_values = self._iv_source.get(key, ())
        if not source_values and len(normalized_expiry) >= 6:
            month = normalized_expiry[:6]
            candidates = [v for k, v in self._iv_source.items()
                          if k[0].startswith(month) and k[1] == option_type and k[2] == strike]
            if len(candidates) == 1:
                source_values = candidates[0]
        if not source_values:
            return None
        source_times = self._iv_source_times.get(key, ())
        if not source_times and len(normalized_expiry) >= 6:
            month = normalized_expiry[:6]
            candidates = [
                times for k, times in self._iv_source_times.items()
                if k[0].startswith(month) and k[1] == option_type and k[2] == strike
            ]
            if len(candidates) == 1:
                source_times = candidates[0]
        if not source_times:
            return None
        index = bisect_right(source_times, self._as_of) - 1
        return source_values[index][1] if index >= 0 else None

    def get_iv(self, *, expiry: str, option_type: str, strike: Decimal) -> Decimal | None:
        normalized_expiry = str(expiry).replace("-", "")
        option_type = str(option_type).upper()
        strike = Decimal(str(strike))
        exact_key = (normalized_expiry[:8], option_type, strike)
        value = self._latest(
            self._iv.get(exact_key, ()),
            self._iv_times.get(exact_key, ()),
            self._as_of,
        )
        if value is not None:
            return value
        if len(normalized_expiry) < 6:
            return None
        month = normalized_expiry[:6]
        candidates = [
            values
            for key, values in self._iv.items()
            if key[0].startswith(month) and key[1] == option_type and key[2] == strike
        ]
        if len(candidates) != 1:
            return None
        candidate_key = next(
            key for key, candidate_values in self._iv.items()
            if candidate_values is candidates[0]
        )
        return self._latest(
            candidates[0],
            self._iv_times[candidate_key],
            self._as_of,
        )

    def get_delta(
        self, *, expiry: str, option_type: str, strike: Decimal, as_of: datetime | None = None,
        instrument_id: str | None = None,
    ) -> Decimal | None:
        values = self._delta_by_instrument.get(str(instrument_id), ()) if instrument_id else ()
        if not values:
            normalized_expiry = str(expiry).replace("-", "")
            key = (normalized_expiry[:8], str(option_type).upper(), Decimal(str(strike)))
            values = self._delta.get(key, ())
            if not values and len(normalized_expiry) == 6:
                candidates = [
                    candidate_values
                    for candidate_key, candidate_values in self._delta.items()
                    if candidate_key[0].startswith(normalized_expiry)
                    and candidate_key[1] == str(option_type).upper()
                    and candidate_key[2] == Decimal(str(strike))
                ]
                if len(candidates) == 1:
                    values = candidates[0]
        if as_of is None:
            as_of = self._as_of
        if as_of is None or not values:
            return None
        times = (
            self._delta_by_instrument_times.get(str(instrument_id), ())
            if instrument_id and values is self._delta_by_instrument.get(str(instrument_id), ())
            else self._delta_times.get(key, ())
        )
        if not times and values:
            times = [item[0] for item in values]
        index = bisect_right(times, as_of) - 1
        return values[index][1] if index >= 0 else None

    def get_order_book(self, symbol: str) -> OptionOrderBookSnapshot | None:
        key = str(symbol).strip()
        return self._latest(
            self._books.get(key, ()),
            self._book_times.get(key, ()),
            self._as_of,
        )
