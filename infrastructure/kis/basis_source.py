from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from contracts.basis_source import BasisObservation
from contracts.kis_index_price_source import KISIndexPriceObservation, KISIndexPriceSource


class KISBasisSource:
    """Derive KOSPI200 basis only from authoritative futures and index observations."""

    def __init__(self, *, index_source: KISIndexPriceSource | None = None, max_time_delta_seconds: float = 2.0) -> None:
        self._index_source = index_source
        self._max_time_delta_seconds = max_time_delta_seconds
        self._futures: BasisObservation | None = None
        self._index: KISIndexPriceObservation | None = None
        self._latest: dict[str, BasisObservation] = {}

    def update(self, observation: BasisObservation) -> None:
        symbol = observation.symbol.strip()
        if not symbol or not observation.source.strip():
            raise ValueError("AUTHORITATIVE_BASIS_IDENTITY_REQUIRED")
        if observation.futures_price <= 0 or observation.spot_price <= 0:
            raise ValueError("AUTHORITATIVE_BASIS_PRICES_REQUIRED")
        self._latest[symbol] = observation

    def update_futures(self, *, price: Decimal, observed_at: datetime, source: str, contract_symbol: str) -> None:
        if price <= 0 or not source.strip() or not contract_symbol.strip():
            raise ValueError("AUTHORITATIVE_FUTURES_BASIS_OBSERVATION_REQUIRED")
        self._futures = BasisObservation("KOSPI200", price, Decimal("1"), observed_at.strftime("%H%M%S"), source)
        self._futures_observed_at = observed_at
        self._futures_contract_symbol = contract_symbol.strip()

    def update_index(self, observation: KISIndexPriceObservation) -> None:
        if observation.underlying_symbol != "KOSPI200" or observation.index_code != "2001":
            raise ValueError("KIS_INDEX_PRICE_IDENTITY_MISMATCH")
        if observation.price <= 0 or not observation.source.strip():
            raise ValueError("KIS_INDEX_PRICE_OBSERVATION_REQUIRED")
        self._index = observation

    def refresh_index(self) -> KISIndexPriceObservation:
        if self._index_source is None:
            raise RuntimeError("KIS_INDEX_PRICE_SOURCE_UNAVAILABLE")
        observation = self._index_source.refresh()
        self.update_index(observation)
        return observation

    def _derived_basis(self) -> Decimal | None:
        if self._futures is None or self._index is None:
            return None
        delta = abs((self._futures_observed_at - self._index.observed_at).total_seconds())
        if delta > self._max_time_delta_seconds:
            return None
        return self._futures.futures_price - self._index.price

    def get_basis(self, symbol: str) -> Decimal | None:
        derived = self._derived_basis()
        if derived is not None:
            return derived
        observation = self._latest.get(str(symbol).strip())
        if observation is None:
            return None
        return observation.futures_price - observation.spot_price
