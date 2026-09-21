from collections.abc import Iterable
from typing import Callable, List, Optional

from contracts.types import MarketObservation
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick
from environments.virtual.market.historical_market_store import HistoricalMarketStore


class HistoricalReplayEngine:
    def __init__(self, ticks: Optional[Iterable[ReferenceCanonicalMarketTick]] = None) -> None:
        self._ticks: List[ReferenceCanonicalMarketTick] = list(ticks or [])
        self._cursor = 0

    @classmethod
    def from_store(cls, store: HistoricalMarketStore, *, source: str | None = None) -> "HistoricalReplayEngine":
        return cls(store.load_ticks(source=source))

    @classmethod
    def from_observation_store(cls, store: HistoricalMarketStore, *, source: str | None = None) -> "HistoricalReplayEngine":
        observations = store.load_observations()
        if source is not None:
            observations = [item for item in observations if item.source == source]
        return cls(cls.project_observation(item) for item in observations)

    @property
    def active(self) -> bool:
        return bool(self._ticks)

    @property
    def exhausted(self) -> bool:
        return self._cursor >= len(self._ticks)

    @property
    def cursor(self) -> int:
        return self._cursor

    def load(self, ticks: Iterable[ReferenceCanonicalMarketTick]) -> None:
        self._ticks = list(ticks)
        self._cursor = 0

    def load_store(self, store: HistoricalMarketStore, *, source: str | None = None) -> None:
        self.load(store.load_ticks(source=source))

    def clear(self) -> None:
        self._ticks = []
        self._cursor = 0

    def reset(self) -> None:
        self._cursor = 0

    @staticmethod
    def project_observation(observation: MarketObservation) -> ReferenceCanonicalMarketTick:
        quote = observation.quote
        if (
            quote.last is None
            or quote.bid is None
            or quote.ask is None
            or quote.volume is None
            or observation.contract.strike is None
            or observation.contract.option_type is None
        ):
            raise ValueError("LEGACY_TICK_REQUIRED_MARKET_VALUE_MISSING")
        replay_time = observation.observed_at or observation.collected_at
        return ReferenceCanonicalMarketTick(
            timestamp=replay_time.isoformat(),
            strike_price=float(observation.contract.strike),
            option_type=observation.contract.option_type,
            contract_multiplier=(
                float(observation.contract.contract_multiplier)
                if observation.contract.contract_multiplier is not None else None
            ),
            bid_price=float(quote.bid),
            ask_price=float(quote.ask),
            last_price=float(quote.last),
            volume=int(quote.volume) if quote.volume is not None else 0,
            expiry=observation.contract.expiry or "",
            symbol=observation.contract.symbol,
        )

    def replay(self, *, speed: float = 1.0, sleep: Callable[[float], None] | None = None) -> list[ReferenceCanonicalMarketTick]:
        if speed <= 0:
            raise ValueError("REPLAY_SPEED_MUST_BE_POSITIVE")
        events = []
        previous = None
        for tick in self._ticks:
            if sleep is not None and previous is not None:
                from datetime import datetime
                delta = (datetime.fromisoformat(tick.timestamp) - datetime.fromisoformat(previous.timestamp)).total_seconds()
                if delta > 0:
                    sleep(delta / speed)
            events.append(tick)
            previous = tick
            self._cursor += 1
        return events

    def next_tick(self) -> Optional[ReferenceCanonicalMarketTick]:
        if self.exhausted:
            return None
        tick = self._ticks[self._cursor]
        self._cursor += 1
        return tick
