from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from contracts.option_expiry import CanonicalOptionExpiryError, require_exact_option_expiry


@dataclass(frozen=True)
class Track9IVObservation:
    """One source-owned IV observation for one option contract."""
    symbol: str
    expiry: str
    option_type: str
    strike: Decimal
    implied_volatility: Decimal
    observed_at: datetime
    source: str

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "expiry", require_exact_option_expiry(self.expiry))
        except CanonicalOptionExpiryError as exc:
            raise ValueError("OPTION_EXPIRY_EXACT_DATE_REQUIRED") from exc


class Track9IVTimeSeriesSource(Protocol):
    """Authoritative append/query boundary for Track9 IV history.

    Query uses the half-open interval [start, end). Implementations must be
    append-only and idempotent for an identical observation identity.
    """
    def append(self, observation: Track9IVObservation) -> None: ...

    def query(
        self,
        *,
        symbol: str,
        expiry: str,
        option_type: str,
        strike: Decimal,
        start: datetime,
        end: datetime,
    ) -> tuple[Track9IVObservation, ...]: ...

    # Duplicate identity is (symbol, expiry, option_type, strike, observed_at, source).
    # Same identity with different payload must be rejected, never overwritten.


class UnavailableTrack9IVTimeSeriesSource:
    """Fail-closed boundary used until an authoritative history store exists."""

    def append(self, observation: Track9IVObservation) -> None:
        raise RuntimeError("TRACK9_IV_TIMESERIES_UNAVAILABLE")

    def query(
        self,
        *,
        symbol: str,
        expiry: str,
        option_type: str,
        strike: Decimal,
        start: datetime,
        end: datetime,
    ) -> tuple[Track9IVObservation, ...]:
        return ()
