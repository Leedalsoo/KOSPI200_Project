from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class Track2OptionIVObservation:
    symbol: str
    expiry: str
    option_type: str
    strike: Decimal
    implied_volatility: Decimal
    observed_at: datetime
    source: str


class Track2OptionIVSource(Protocol):
    def get_iv(
        self, *, expiry: str, option_type: str, strike: Decimal
    ) -> Decimal | None: ...


class UnavailableTrack2OptionIVSource:
    def get_iv(
        self, *, expiry: str, option_type: str, strike: Decimal
    ) -> Decimal | None:
        return None
