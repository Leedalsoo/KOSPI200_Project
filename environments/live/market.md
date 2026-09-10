KIS Live MarketDataProvider 경계. KIS FUTURES WebSocket consumer의 typed observation을 Standard MarketState로 투영하는 Environment 경계이며, instrument_id와 observed_at은 외부 authoritative provider를 명시적으로 주입한다. synthetic identity/time fallback은 금지한다.

[Child Page] kis_futures_market_data.py
```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from contracts.types import CanonicalMarketTick, DataQuality, MarketState, ProviderHealth
from contracts.kis_index_futures_market_ws_adapter import KisIndexFuturesMarketObservation


class KISFuturesMarketProjectionError(ValueError):
    """Raised when KIS FUTURES data cannot be projected safely."""


InstrumentIdResolver = Callable[[str], str]
ObservedAtResolver = Callable[[KisIndexFuturesMarketObservation], datetime]
MarketStateSubscriber = Callable[[MarketState], None]


@dataclass
class KISFuturesMarketDataProvider:
    """Environment boundary from typed KIS FUTURES observations to MarketState.

    Standard instrument identity and observation timestamp are authoritative
    inputs. This provider never derives either value from broker short codes
    or local wall-clock fallbacks.
    """

    instrument_id_resolver: InstrumentIdResolver | None = None
    observed_at_resolver: ObservedAtResolver | None = None
    _ticks: dict[str, CanonicalMarketTick] = field(default_factory=dict)
    _quality: dict[str, DataQuality] = field(default_factory=dict)
    _subscribers: list[MarketStateSubscriber] = field(default_factory=list)
    _as_of: datetime | None = None

    def publish(self, observation: KisIndexFuturesMarketObservation) -> CanonicalMarketTick:
        if self.instrument_id_resolver is None:
            raise KISFuturesMarketProjectionError("FUTURES_INSTRUMENT_ID_RESOLVER_REQUIRED")
        if self.observed_at_resolver is None:
            raise KISFuturesMarketProjectionError("FUTURES_OBSERVED_AT_RESOLVER_REQUIRED")

        instrument_id = self.instrument_id_resolver(observation.shrn_iscd.strip())
        if not instrument_id:
            raise KISFuturesMarketProjectionError("FUTURES_INSTRUMENT_ID_REQUIRED")
        observed_at = self.observed_at_resolver(observation)
        if not isinstance(observed_at, datetime):
            raise KISFuturesMarketProjectionError("FUTURES_OBSERVED_AT_REQUIRED")
        if observation.price is None:
            raise KISFuturesMarketProjectionError("FUTURES_LAST_PRICE_REQUIRED")

        tick = CanonicalMarketTick(
            instrument_id=instrument_id,
            observed_at=observed_at,
            price=observation.price,
            volume=observation.volume,
            source_sequence=None,
        )
        quality = DataQuality(
            is_fresh=True,
            is_complete=observation.volume is not None,
            source_available=True,
            reason=None,
        )
        self._ticks[instrument_id] = tick
        self._quality[instrument_id] = quality
        self._as_of = observed_at
        state = self.snapshot()
        for subscriber in tuple(self._subscribers):
            subscriber(state)
        return tick

    def snapshot(self) -> MarketState:
        if self._as_of is None:
            raise KISFuturesMarketProjectionError("FUTURES_MARKET_STATE_UNAVAILABLE")
        return MarketState(
            as_of=self._as_of,
            ticks=dict(self._ticks),
            quality=dict(self._quality),
        )

    def subscribe(self, callback: MarketStateSubscriber) -> None:
        self._subscribers.append(callback)

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            available=self._as_of is not None,
            as_of=self._as_of,
            reason=None if self._as_of is not None else "FUTURES_MARKET_STATE_UNAVAILABLE",
        )
```
## 책임 경계
    - KISIndexFuturesMarketConsumer의 typed observation을 Standard MarketState로 변환하는 실제 Environment 경계다.
    - shrn_iscd는 Market subscription identity로만 입력되며 Standard instrument_id를 직접 생성하지 않는다.
    - instrument_id는 authoritative resolver를 통해서만 공급된다.
    - KIS observed_hour를 임의 날짜나 로컬 현재시각과 조합하지 않는다. observed_at은 명시적 resolver가 공급한다.
    - price가 없는 quote-only observation은 Standard tick으로 승격하지 않고 fail-closed한다.
    - source_sequence를 synthetic sequence로 생성하지 않는다.
    - 변환 결과는 MarketDataProvider contract의 MarketState/ProviderHealth로 노출된다.