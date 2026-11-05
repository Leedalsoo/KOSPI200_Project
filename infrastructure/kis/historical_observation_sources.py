from __future__ import annotations
from bisect import bisect_right
from datetime import datetime, time as datetime_time, timedelta
from decimal import Decimal, InvalidOperation
import re
from zoneinfo import ZoneInfo
from typing import Sequence
from contracts.market_data_freshness import FreshnessEvidence
from contracts.option_orderbook_source import OptionOrderBookSnapshot, OptionOrderBookLevel
from contracts.track2_option_iv_source import Track2OptionIVSource
from contracts.types import MarketObservation

class HistoricalObservationOptionSource(Track2OptionIVSource):
    """Replay-time option IV/order-book/Greeks source backed only by historical observations."""
    @staticmethod
    def _freshness_timestamp(observation: MarketObservation) -> datetime | None:
        """Return a verified source timestamp, or None when semantics are unverified.

        KIS REST and WebSocket HHMMSS values are retained in provenance as candidate
        timestamps only. Neither is promoted to an absolute source time until its
        semantics are independently verified and a freshness threshold is approved.
        """
        return None
    def __init__(self, observations: Sequence[MarketObservation]) -> None:
        self._as_of: datetime | None = None
        self._iv: dict[tuple[str, str, Decimal], list[tuple[datetime, Decimal]]] = {}
        self._iv_source: dict[tuple[str, str, Decimal], list[tuple[datetime, str]]] = {}
        self._delta: dict[tuple[str, str, Decimal], list[tuple[datetime, Decimal]]] = {}
        self._delta_by_instrument: dict[str, list[tuple[datetime, Decimal]]] = {}
        self._books: dict[str, list[tuple[datetime, OptionOrderBookSnapshot, datetime | None]]] = {}
        self._quotes: dict[str, list[tuple[datetime, object, datetime | None]]] = {}
        self._contracts_by_symbol: dict[str, object] = {}
        self._observations_by_symbol: dict[str, list[MarketObservation]] = {}
        self._iv_times: dict[tuple[str, str, Decimal], list[datetime]] = {}
        self._iv_source_times: dict[tuple[str, str, Decimal], list[datetime]] = {}
        self._delta_times: dict[tuple[str, str, Decimal], list[datetime]] = {}
        self._delta_by_instrument_times: dict[str, list[datetime]] = {}
        self._book_times: dict[str, list[datetime]] = {}
        for observation in observations:
            observed_at = observation.observed_at or observation.collected_at
            if observed_at is None:
                continue
            freshness_at = self._freshness_timestamp(observation)
            identity = observation.contract
            symbol = str(identity.symbol)
            self._observations_by_symbol.setdefault(symbol, []).append(observation)
            self._contracts_by_symbol[symbol] = identity
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
            quote = observation.quote
            if quote is not None:
                self._quotes.setdefault(str(identity.symbol), []).append((observed_at, quote, freshness_at))
            book = observation.order_book
            if book is not None:
                ask_levels = self._valid_order_book_levels(book.asks)
                bid_levels = self._valid_order_book_levels(book.bids)
                if len(bid_levels) >= 5 and len(ask_levels) >= 5:
                    snapshot = OptionOrderBookSnapshot(
                        symbol=str(identity.symbol),
                        observed_hour=observed_at.strftime("%H%M%S%f").rstrip("0"),
                        ask_levels=ask_levels[:5],
                        bid_levels=bid_levels[:5],
                        source=f"HistoricalObservationStore:{observation.source}",
                    )
                    self._books.setdefault(str(identity.symbol), []).append(
                        (observed_at, snapshot, freshness_at)
                    )
        for values in self._iv.values():
            values.sort(key=lambda item: item[0])
        for values in self._delta.values():
            values.sort(key=lambda item: item[0])
        for values in self._delta_by_instrument.values():
            values.sort(key=lambda item: item[0])
        for values in self._books.values():
            values.sort(key=lambda item: item[0])
        for values in self._quotes.values():
            values.sort(key=lambda item: item[0])
        self._iv_times = {key: [item[0] for item in values] for key, values in self._iv.items()}
        self._iv_source_times = {key: [item[0] for item in values] for key, values in self._iv_source.items()}
        self._delta_times = {key: [item[0] for item in values] for key, values in self._delta.items()}
        self._delta_by_instrument_times = {
            key: [item[0] for item in values] for key, values in self._delta_by_instrument.items()
        }
        self._book_times = {key: [item[0] for item in values] for key, values in self._books.items()}

    @staticmethod
    def _valid_order_book_levels(levels) -> tuple[OptionOrderBookLevel, ...]:
        valid = []
        for level in levels:
            try:
                price = Decimal(str(level.price))
                quantity = Decimal(str(level.quantity))
            except (InvalidOperation, TypeError, ValueError):
                continue
            if not price.is_finite() or not quantity.is_finite() or price <= 0 or quantity < 0:
                continue
            valid.append(OptionOrderBookLevel(price=price, quantity=quantity))
        return tuple(valid)

    def set_as_of(self, observed_at: datetime) -> None:
        self._as_of = observed_at

    def get_freshness_evidence(self, symbol: str, *, as_of: datetime | None = None) -> FreshnessEvidence | None:
        """Expose provenance for the latest eligible observation without promoting its time to verified source time."""
        key = str(symbol).strip()
        target = as_of or self._as_of
        if not key or target is None:
            return None
        eligible = []
        for observation in self._observations_by_symbol.get(key, ()):
            observed_at = observation.observed_at or observation.collected_at
            if observed_at is None:
                continue
            try:
                if observed_at <= target:
                    eligible.append((observed_at, observation))
            except TypeError:
                # Naive/aware timestamp mixtures are not comparable evidence.
                continue
        if not eligible:
            return None
        observation = max(eligible, key=lambda item: item[0])[1]
        provenance = observation.provenance
        metadata = dict(getattr(provenance, "metadata", ()) or ())
        raw_reference = getattr(observation, "raw_reference", None)
        source_times = tuple(getattr(provenance, "source_timestamps", ()) or ())
        endpoints = tuple(getattr(provenance, "endpoints", ()) or ())
        tr_ids = tuple(getattr(provenance, "tr_ids", ()) or ())
        contract = observation.contract
        return FreshnessEvidence(
            source=str(getattr(observation, "source", "") or ""),
            endpoint=str(endpoints[0] if endpoints else ""),
            tr_id=str(tr_ids[0] if tr_ids else ""),
            environment=str(metadata.get("environment", metadata.get("kis_environment", "")) or ""),
            instrument_id=str(getattr(contract, "instrument_id", "") or ""),
            symbol=str(getattr(contract, "symbol", "") or ""),
            raw_source_time=str(source_times[0] if source_times else ""),
            source_instant=self._freshness_timestamp(observation),
            received_at=getattr(observation, "collected_at", None),
            raw_payload_sha256=getattr(raw_reference, "content_hash", None),
            source_time_semantics_verified=False,
            capability_verified=False,
            metadata={"evidence_origin": "HistoricalObservationOptionSource", "source_time_status": "UNVERIFIED"},
        )

    @staticmethod
    def _latest(values, timestamps, as_of: datetime | None):
        if as_of is None or not values:
            return None
        index = bisect_right(timestamps, as_of) - 1
        return values[index][1] if index >= 0 else None

    def get_iv_source(self, *, expiry: str, option_type: str, strike: Decimal):
        from contracts.option_expiry import CanonicalOptionExpiryError, require_exact_option_expiry
        try:
            normalized_expiry = require_exact_option_expiry(expiry)
        except CanonicalOptionExpiryError:
            return None
        option_type = str(option_type).upper()
        strike = Decimal(str(strike))
        key = (normalized_expiry, option_type, strike)
        values = self._iv.get(key, ())
        if self._as_of is None or not values:
            return None
        source_values = self._iv_source.get(key, ())
        source_times = self._iv_source_times.get(key, ())
        if not source_values or not source_times:
            return None
        index = bisect_right(source_times, self._as_of) - 1
        return source_values[index][1] if index >= 0 else None

    def get_iv(self, *, expiry: str, option_type: str, strike: Decimal) -> Decimal | None:
        from contracts.option_expiry import CanonicalOptionExpiryError, require_exact_option_expiry
        try:
            normalized_expiry = require_exact_option_expiry(expiry)
        except CanonicalOptionExpiryError:
            return None
        option_type = str(option_type).upper()
        strike = Decimal(str(strike))
        exact_key = (normalized_expiry, option_type, strike)
        return self._latest(
            self._iv.get(exact_key, ()),
            self._iv_times.get(exact_key, ()),
            self._as_of,
        )

    def get_delta(
        self, *, expiry: str, option_type: str, strike: Decimal, as_of: datetime | None = None,
        instrument_id: str | None = None,
    ) -> Decimal | None:
        from contracts.option_expiry import CanonicalOptionExpiryError, require_exact_option_expiry
        try:
            normalized_expiry = require_exact_option_expiry(expiry)
        except CanonicalOptionExpiryError:
            return None
        values = self._delta_by_instrument.get(str(instrument_id), ()) if instrument_id else ()
        key = (normalized_expiry, str(option_type).upper(), Decimal(str(strike)))
        if not values:
            values = self._delta.get(key, ())
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

    def latest_authoritative_option_quotes(self, as_of: datetime | None = None) -> dict[tuple[str, float, str], dict]:
        """Return only executable quotes evidenced by the historical observation store.

        This is a source-side DTO boundary. It does not know or import the VMS.
        Missing/invalid bid-ask evidence is omitted rather than synthesized.
        """
        if as_of is None:
            as_of = self._as_of
        if as_of is None:
            return {}
        result: dict[tuple[str, float, str], dict] = {}
        for symbol, books in self._books.items():
            snapshot = self._latest(books, self._book_times.get(symbol, ()), as_of)
            if snapshot is None or not snapshot.bid_levels or not snapshot.ask_levels:
                continue
            bid = Decimal(str(snapshot.bid_levels[0].price))
            ask = Decimal(str(snapshot.ask_levels[0].price))
            if bid <= 0 or ask <= 0 or ask < bid:
                continue
            identity = self._contracts_by_symbol.get(symbol)
            if identity is None or identity.contract_multiplier is None:
                continue
            quote_values = self._quotes.get(symbol, ())
            quote_times = [item[0] for item in quote_values]
            quote = self._latest(quote_values, quote_times, as_of) if quote_values else None
            last = getattr(quote, "last", None) if quote is not None else None
            expiry = str(identity.expiry).replace("-", "")[:8]
            if len(expiry) != 8 or identity.option_type not in {"CALL", "PUT"} or identity.strike is None:
                continue
            result[(str(identity.option_type).upper(), float(identity.strike), expiry)] = {
                "bid": bid,
                "ask": ask,
                "last": Decimal(str(last)) if last is not None else None,
                "timestamp": snapshot.observed_hour,
                "contract_multiplier": Decimal(str(identity.contract_multiplier)),
                "shrn_iscd": str(identity.symbol),
                "source": snapshot.source,
            }
        return result

    def get_order_book_with_timestamp(
        self, symbol: str, *, as_of: datetime | None = None
    ) -> tuple[OptionOrderBookSnapshot | None, datetime | None]:
        """Return the latest KIS book and verified freshness timestamp, if available.

        Unverified REST/WebSocket HHMMSS values and local receipt time are not
        treated as verified source timestamps; freshness remains UNKNOWN (None).
        """
        key = str(symbol).strip()
        target = as_of or self._as_of
        values = self._books.get(key, ())
        times = self._book_times.get(key, ())
        if target is None or not values or not times:
            return None, None
        index = bisect_right(times, target) - 1
        if index < 0:
            return None, None
        observed_at, snapshot, freshness_at = values[index]
        return snapshot, freshness_at

    def get_volume_with_timestamp(
        self, symbol: str, *, as_of: datetime | None = None
    ) -> tuple[Decimal | None, datetime | None]:
        """Return the latest non-null KIS-reported volume without filling gaps."""
        key = str(symbol).strip()
        target = as_of or self._as_of
        values = self._quotes.get(key, ())
        if target is None or not values:
            return None, None
        times = [item[0] for item in values]
        index = bisect_right(times, target) - 1
        for candidate_index in range(index, -1, -1):
            observed_at, quote, freshness_at = values[candidate_index]
            value = getattr(quote, "volume", None)
            if value is None:
                continue
            try:
                volume = Decimal(str(value))
            except (InvalidOperation, TypeError, ValueError):
                continue
            if volume.is_finite() and volume >= 0:
                return volume, freshness_at
        return None, None

    def get_order_book(self, symbol: str) -> OptionOrderBookSnapshot | None:
        book, _ = self.get_order_book_with_timestamp(symbol)
        return book
