from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

KOSPI200_INDEX_CODE = "2001"
KIS_INDEX_PRICE_TR_ID = "FHPUP02100000"
KIS_INDEX_PRICE_PATH = "/uapi/domestic-stock/v1/quotations/inquire-index-price"


@dataclass(frozen=True)
class KISIndexPriceObservation:
    underlying_symbol: str
    index_code: str
    price: Decimal
    observed_at: datetime
    source: str
    tr_id: str = KIS_INDEX_PRICE_TR_ID


class KISIndexPriceSource(Protocol):
    def get_latest(self, underlying_symbol: str = "KOSPI200") -> KISIndexPriceObservation | None: ...
