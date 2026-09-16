from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from contracts.kis_index_futures_market_ws_adapter import (
    KisIndexFuturesMarketObservation,
)


class UnderlyingMarketStateError(ValueError):
    """Raised when authoritative underlying state cannot be established."""


@dataclass(frozen=True)
class AuthoritativeUnderlyingMarketState:
    symbol: str
    observed_hour: str
    price: Decimal
    source: str


class KISUnderlyingMarketState:
    """Hold the latest authoritative KIS underlying futures price."""

    def __init__(self) -> None:
        self._state: AuthoritativeUnderlyingMarketState | None = None

    @property
    def state(self) -> AuthoritativeUnderlyingMarketState | None:
        return self._state

    def update(self, observation: KisIndexFuturesMarketObservation) -> None:
        if observation.price is None:
            return
        if not observation.shrn_iscd.strip():
            raise UnderlyingMarketStateError("AUTHORITATIVE_UNDERLYING_SYMBOL_REQUIRED")
        if not observation.source.strip():
            raise UnderlyingMarketStateError("AUTHORITATIVE_UNDERLYING_SOURCE_REQUIRED")
        self._state = AuthoritativeUnderlyingMarketState(
            symbol=observation.shrn_iscd,
            observed_hour=observation.observed_hour,
            price=observation.price,
            source=observation.source,
        )

    def price_for(self, *, required: bool = True) -> Decimal | None:
        if self._state is None and required:
            raise UnderlyingMarketStateError("AUTHORITATIVE_UNDERLYING_PRICE_REQUIRED")
        return self._state.price if self._state is not None else None
