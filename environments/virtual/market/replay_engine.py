from collections.abc import Iterable
from typing import Callable, List, Optional

from contracts.types import MarketObservation
from environments.virtual.market.canonical import ReferenceCanonicalMarketTick
from environments.virtual.market.historical_market_store import HistoricalMarketStore


class HistoricalReplayEngine:
    def __init__(self, ticks: Optional[Iterable[ReferenceCanonicalMarketTick]] = None) -> None:
        self._ticks: List[ReferenceCanonicalMarketTick] = list(ticks or [])
        self._cursor = 0
        self._projection_errors: list[dict[str, str]] = []

    @property
    def projection_errors(self) -> tuple[dict[str, str], ...]:
        return tuple(self._projection_errors)

    @classmethod
    def from_store(cls, store: HistoricalMarketStore, *, source: str | None = None) -> "HistoricalReplayEngine":
        return cls(store.load_ticks(source=source))

    @classmethod
    def from_observation_store(cls, store: HistoricalMarketStore, *, source: str | None = None) -> "HistoricalReplayEngine":
        observations = store.load_observations()
        if source is not None:
            observations = [item for item in observations if item.source == source]
        engine = cls()
        ticks: list[ReferenceCanonicalMarketTick] = []
        projection_errors: list[dict[str, str]] = []
        for index, observation in enumerate(observations, start=1):
            try:
                ticks.append(cls.project_observation(observation, seq_id=index))
            except ValueError as exc:
                # A malformed quote is excluded with explicit evidence; identity/schema
                # errors remain fatal and are not silently filtered.
                if str(exc) != "CANONICAL_QUOTE_REQUIRED_FIELDS_MISSING":
                    raise
                projection_errors.append({
                    "observation_id": observation.observation_id,
                    "reason": str(exc),
                })
        engine.load(ticks)
        engine._projection_errors = projection_errors
        return engine

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
        self._projection_errors = []

    def load_store(self, store: HistoricalMarketStore, *, source: str | None = None) -> None:
        self.load(store.load_ticks(source=source))

    def clear(self) -> None:
        self._ticks = []
        self._cursor = 0

    def reset(self) -> None:
        self._cursor = 0

    @staticmethod
    def project_observation(observation: MarketObservation, *, seq_id: int = 0) -> ReferenceCanonicalMarketTick:
        quote = observation.quote
        if (
            quote.bid is None
            or quote.ask is None
            or float(quote.bid) <= 0
            or float(quote.ask) <= 0
            or float(quote.ask) < float(quote.bid)
            or observation.contract.strike is None
            or observation.contract.option_type is None
        ):
            raise ValueError("CANONICAL_QUOTE_REQUIRED_FIELDS_MISSING")
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
            last_price=float(quote.last) if quote.last is not None else None,
            volume=int(quote.volume) if quote.volume is not None else None,
            seq_id=seq_id,
            expiry=observation.contract.expiry or "",
            symbol=observation.contract.symbol,
            instrument_id=observation.contract.instrument_id,
            underlying_price=float(observation.underlying_price) if observation.underlying_price is not None else None,
            underlying_symbol=observation.underlying_symbol,
            underlying_observed_hour=observation.underlying_observed_hour,
            underlying_source=observation.underlying_source,
            implied_volatility=float(observation.analytics.implied_volatility) if observation.analytics.implied_volatility is not None else None,
            delta=float(observation.analytics.delta) if observation.analytics.delta is not None else None,
            gamma=float(observation.analytics.gamma) if observation.analytics.gamma is not None else None,
            theta=float(observation.analytics.theta) if observation.analytics.theta is not None else None,
            vega=float(observation.analytics.vega) if observation.analytics.vega is not None else None,
            option_observed_hour=(observation.provenance.source_timestamps[0] if observation.provenance.source_timestamps else ""),
            option_source=observation.source,
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
