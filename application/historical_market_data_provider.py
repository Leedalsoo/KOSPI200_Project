"""MarketDataProvider adapter for the existing HistoricalReplayEngine."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

from contracts.market_data import MarketDataSubscriber
from contracts.types import CanonicalMarketTick, DataQuality, MarketState, ProviderHealth
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick
from environments.virtual.market.replay_engine import HistoricalReplayEngine


@dataclass
class HistoricalMarketDataProvider:
    """Expose historical replay through the standard MarketDataProvider contract."""

    replay: HistoricalReplayEngine
    _ticks: dict[str, CanonicalMarketTick] = field(default_factory=dict)
    _quality: dict[str, DataQuality] = field(default_factory=dict)
    _subscribers: list[MarketDataSubscriber] = field(default_factory=list)
    _as_of: datetime | None = None
    _source: str | None = None

    def _project(self, tick: ReferenceCanonicalMarketTick) -> CanonicalMarketTick:
        if not tick.symbol and not tick.underlying_symbol:
            raise ValueError("HISTORICAL_INSTRUMENT_ID_REQUIRED")
        observed_at = datetime.fromisoformat(tick.timestamp)
        price = tick.underlying_price if tick.underlying_price is not None else tick.last_price
        if price is None or float(price) <= 0:
            raise ValueError("HISTORICAL_PRICE_REQUIRED")
        instrument_id = tick.symbol or tick.underlying_symbol
        canonical = CanonicalMarketTick(
            instrument_id=instrument_id,
            observed_at=observed_at,
            price=Decimal(str(price)),
            volume=Decimal(str(tick.volume)) if tick.volume is not None else None,
            source_sequence=tick.seq_id or None,
            seq_id=tick.seq_id or None,
            underlying_price=Decimal(str(tick.underlying_price)) if tick.underlying_price is not None else None,
            underlying_symbol=tick.underlying_symbol,
            underlying_observed_hour=tick.underlying_observed_hour,
            underlying_source=tick.underlying_source,
        )
        self._ticks[instrument_id] = canonical
        self._quality[instrument_id] = DataQuality(
            is_fresh=True, is_complete=True, source_available=True, reason=None
        )
        self._as_of = observed_at
        self._source = tick.option_source or tick.underlying_source or "HISTORICAL_REPLAY"
        return canonical

    def publish(self, tick: ReferenceCanonicalMarketTick) -> CanonicalMarketTick:
        canonical = self._project(tick)
        state = self.snapshot()
        for subscriber in tuple(self._subscribers):
            subscriber(state)
        return canonical

    def replay_next(self) -> CanonicalMarketTick | None:
        tick = self.replay.next_tick()
        if tick is None:
            return None
        return self.publish(tick)

    def snapshot(self) -> MarketState:
        if self._as_of is None:
            raise ValueError("HISTORICAL_MARKET_STATE_UNAVAILABLE")
        return MarketState(
            as_of=self._as_of,
            ticks=dict(self._ticks),
            quality=dict(self._quality),
        )

    def subscribe(self, callback: MarketDataSubscriber) -> None:
        if not callable(callback):
            raise TypeError("HISTORICAL_MARKET_SUBSCRIBER_REQUIRED")
        self._subscribers.append(callback)

    def health(self) -> ProviderHealth:
        if self._as_of is None:
            return ProviderHealth(
                available=False,
                reason="HISTORICAL_MARKET_STATE_UNAVAILABLE",
            )
        now = datetime.now(timezone.utc)
        observed_at = self._as_of
        if observed_at.tzinfo is None:
            now = datetime.now()
        freshness_seconds = max(0.0, (now - observed_at).total_seconds())
        return ProviderHealth(
            available=True,
            as_of=observed_at,
            source=self._source,
            observed_at=observed_at,
            freshness_seconds=freshness_seconds,
        )
