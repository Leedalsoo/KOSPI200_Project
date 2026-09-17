from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Protocol


@dataclass(frozen=True)
class Track3RuntimeInput:
    """Authoritative Track3 values supplied by a Virtual runtime source."""

    observed_at: datetime
    spread_history: tuple[float, ...]
    active_vol: float
    base_vol: float
    price_change_rate: float
    bid_ask_spread: float
    gap_pct: float
    is_gap: bool
    market_stable: bool
    spread_normalizing: bool
    allow_size_up: bool
    total_fees: float
    premium_spent: float
    options_legs: tuple[Mapping[str, object], ...]
    contract_multiplier: float | None
    source: str


class Track3RuntimeInputSource(Protocol):
    """Authoritative source boundary; no source means unavailable."""

    def get_input(self, symbol: str, observed_at: datetime) -> Track3RuntimeInput | None: ...


class UnavailableTrack3RuntimeInputSource:
    def get_input(self, symbol: str, observed_at: datetime) -> Track3RuntimeInput | None:
        return None
