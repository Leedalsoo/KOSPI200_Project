from __future__ import annotations

from decimal import Decimal
from typing import Callable, Sequence

from .track4_kis_greeks_provider import Track4KisGreeksProvider

from core.sensor.market_condition_sensor import MarketConditionSnapshot

from .track4_runtime_input_provider import (
    Track4InputSourceUnavailable,
    Track4RuntimeInputProvider,
    Track4RuntimeInputReadiness,
)


class Track4MarketProjectionProvider(Track4RuntimeInputProvider):
    """Read-only Track4 market provider backed by authoritative Sensor projections."""

    def __init__(
        self,
        snapshot_supplier: Callable[[], MarketConditionSnapshot | None],
        price_history_supplier: Callable[[str], Sequence[float]] | None = None,
        greeks_provider: Track4KisGreeksProvider | None = None,
    ) -> None:
        self._snapshot_supplier = snapshot_supplier
        self._price_history_supplier = price_history_supplier
        self._greeks_provider = greeks_provider

    def _snapshot(self) -> MarketConditionSnapshot:
        snapshot = self._snapshot_supplier()
        if snapshot is None:
            raise Track4InputSourceUnavailable("market condition snapshot is unavailable")
        return snapshot

    def readiness(self) -> Track4RuntimeInputReadiness:
        snapshot = self._snapshot_supplier()
        history_ready = False
        if snapshot is not None and self._price_history_supplier is not None:
            history_ready = bool(self._price_history_supplier(snapshot.instrument_id))
        return Track4RuntimeInputReadiness(
            market=snapshot is not None,
            history=history_ready,
            account_pnl=False,
            greeks=self._greeks_provider is not None,
            attribution=False,
        )

    def observed_at(self):
        return self._snapshot().as_of

    def current_price(self) -> Decimal:
        return Decimal(str(self._snapshot().current_price))

    def active_vol(self) -> Decimal:
        if self._greeks_provider is not None:
            return self._greeks_provider.active_vol()
        return Decimal(str(self._snapshot().volatility))

    def base_vol(self) -> Decimal:
        return Decimal(str(self._snapshot().baseline_volatility))

    def current_pnl(self) -> Decimal:
        raise Track4InputSourceUnavailable("account/pnl source is unavailable")

    def current_equity(self) -> Decimal:
        raise Track4InputSourceUnavailable("account/equity source is unavailable")

    def price_history(self) -> Sequence[Decimal]:
        snapshot = self._snapshot()
        if self._price_history_supplier is None:
            raise Track4InputSourceUnavailable("observed price history source is unavailable")
        return tuple(Decimal(str(value)) for value in self._price_history_supplier(snapshot.instrument_id))

    def current_delta(self) -> Decimal:
        if self._greeks_provider is None:
            raise Track4InputSourceUnavailable("greeks source is unavailable")
        return self._greeks_provider.current_delta()

    def current_gamma(self) -> Decimal:
        if self._greeks_provider is None:
            raise Track4InputSourceUnavailable("greeks source is unavailable")
        return self._greeks_provider.current_gamma()

    def premium_spent(self) -> Decimal:
        raise Track4InputSourceUnavailable("attribution source is unavailable")

    def accumulated_gamma_profit(self) -> Decimal:
        raise Track4InputSourceUnavailable("attribution source is unavailable")

    def theta_decay_cost(self) -> Decimal:
        raise Track4InputSourceUnavailable("attribution source is unavailable")
