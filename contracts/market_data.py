from typing import Callable, Iterable, Protocol

from contracts.types import MarketState, ProviderHealth


MarketDataSubscriber = Callable[[MarketState], None]


class MarketDataProvider(Protocol):
    """Environment-side market data boundary."""

    def snapshot(self) -> MarketState: ...

    def subscribe(self, callback: MarketDataSubscriber) -> None: ...

    def health(self) -> ProviderHealth: ...
