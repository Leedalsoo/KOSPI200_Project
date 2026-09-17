"""Minimal application boundary for canonical market-data providers."""
from __future__ import annotations

from typing import Callable

from contracts.market_data import MarketDataProvider, MarketDataSubscriber
from contracts.types import MarketState, ProviderHealth


class MarketDataHub:
    """Route one selected MarketDataProvider without changing its contract.

    The first implementation deliberately keeps provider selection outside
    Strategy/Runtime and leaves KIS adapters and Historical Replay untouched.
    Additional providers can be registered later without exposing provider-
    specific API fields beyond the adapter boundary.
    """

    def __init__(self, providers: dict[str, MarketDataProvider], *, active: str) -> None:
        if not providers:
            raise ValueError("MARKET_DATA_HUB_PROVIDER_REQUIRED")
        self._providers = dict(providers)
        self._active = str(active).strip()
        if not self._active or self._active not in self._providers:
            raise ValueError("MARKET_DATA_HUB_ACTIVE_PROVIDER_REQUIRED")

    @property
    def active_provider(self) -> str:
        return self._active

    def provider_names(self) -> tuple[str, ...]:
        return tuple(self._providers)

    def select(self, provider: str) -> None:
        name = str(provider).strip()
        if name not in self._providers:
            raise KeyError(name)
        self._active = name

    def _provider(self) -> MarketDataProvider:
        return self._providers[self._active]

    def snapshot(self) -> MarketState:
        return self._provider().snapshot()

    def subscribe(self, callback: MarketDataSubscriber) -> None:
        self._provider().subscribe(callback)

    def health(self) -> ProviderHealth:
        return self._provider().health()
