from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

KOSPI200_INDEX_CODE = "2001"
KIS_KOSPI200_DAILY_TR_ID = "FHPUP02120000"
KIS_KOSPI200_DAILY_PATH = "/uapi/domestic-stock/v1/quotations/inquire-index-daily-price"


@dataclass(frozen=True)
class KOSPI200DailyContext:
    trading_date: date
    open_price: Decimal
    previous_close: Decimal
    source: str


class KOSPI200DailySource(Protocol):
    def get_context(self, trading_date: date) -> KOSPI200DailyContext | None: ...
