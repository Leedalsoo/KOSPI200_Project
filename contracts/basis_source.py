from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

@dataclass(frozen=True)
class BasisObservation:
    symbol: str
    futures_price: Decimal
    spot_price: Decimal
    observed_hour: str
    source: str

class BasisSource(Protocol):
    def get_basis(self, symbol: str) -> Decimal | None: ...

class UnavailableBasisSource:
    def get_basis(self, symbol: str) -> Decimal | None:
        return None
