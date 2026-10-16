from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from contracts.option_expiry import CanonicalOptionExpiryError, require_exact_option_expiry


@dataclass(frozen=True)
class Track2OptionIVObservation:
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


class Track2OptionIVSource(Protocol):
    def get_iv(
        self, *, expiry: str, option_type: str, strike: Decimal
    ) -> Decimal | None: ...


class UnavailableTrack2OptionIVSource:
    def get_iv(
        self, *, expiry: str, option_type: str, strike: Decimal
    ) -> Decimal | None:
        return None
