from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class Track6VolatilitySnapshot:
    active_vol: Decimal
    base_vol: Decimal
    call_iv: Decimal
    put_iv: Decimal
    strike: Decimal
    expiry: str
    observed_at: datetime
    source: str


class Track6VolatilitySource(Protocol):
    def snapshot(self, *, expiry: str, current_price: Decimal, observed_at: datetime) -> Track6VolatilitySnapshot | None: ...
    def reset_for_new_session(self, session_date) -> None: ...
