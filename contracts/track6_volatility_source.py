from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from contracts.option_expiry import CanonicalOptionExpiryError, require_exact_option_expiry


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

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "expiry", require_exact_option_expiry(self.expiry))
        except CanonicalOptionExpiryError as exc:
            raise ValueError("OPTION_EXPIRY_EXACT_DATE_REQUIRED") from exc


class Track6VolatilitySource(Protocol):
    def snapshot(self, *, expiry: str, current_price: Decimal, observed_at: datetime) -> Track6VolatilitySnapshot | None: ...
    def reset_for_new_session(self, session_date) -> None: ...
