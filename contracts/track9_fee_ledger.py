from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class Track9FeeRecord:
    run_id: str
    strategy_id: str
    group_id: str
    leg_id: str
    client_order_id: str
    execution_id: str
    instrument_id: str
    fee_amount: Decimal
    executed_quantity: int
    executed_price: Decimal
    executed_at: datetime
    source: str

    def __post_init__(self) -> None:
        required = {
            "run_id": self.run_id,
            "strategy_id": self.strategy_id,
            "group_id": self.group_id,
            "leg_id": self.leg_id,
            "client_order_id": self.client_order_id,
            "execution_id": self.execution_id,
            "instrument_id": self.instrument_id,
            "source": self.source,
        }
        if any(not str(value).strip() for value in required.values()):
            raise ValueError("TRACK9_FEE_PROVENANCE_REQUIRED")
        if self.executed_quantity <= 0 or self.executed_price <= 0:
            raise ValueError("TRACK9_FEE_EXECUTION_VALUE_REQUIRED")
        if self.fee_amount < 0:
            raise ValueError("TRACK9_FEE_AMOUNT_INVALID")


class Track9FeeLedger(Protocol):
    def record(self, fee: Track9FeeRecord) -> None: ...

    def query(
        self,
        *,
        run_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> tuple[Track9FeeRecord, ...]: ...

    def total(self, *, run_id: str, start: datetime | None = None,
              end: datetime | None = None) -> Decimal: ...
