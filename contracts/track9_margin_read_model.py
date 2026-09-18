from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class Track9MarginSnapshot:
    run_id: str
    account_id: str
    total_balance: Decimal
    used_margin: Decimal
    free_margin: Decimal
    observed_at: datetime
    source: str

    def __post_init__(self) -> None:
        if not self.run_id.strip() or not self.account_id.strip() or not self.source.strip():
            raise ValueError("TRACK9_MARGIN_PROVENANCE_REQUIRED")
        if self.total_balance <= 0:
            raise ValueError("TRACK9_MARGIN_TOTAL_BALANCE_INVALID")
        if self.used_margin < 0 or self.free_margin < 0:
            raise ValueError("TRACK9_MARGIN_VALUE_INVALID")


class Track9MarginReadModel(Protocol):
    def snapshot(self, *, run_id: str) -> Track9MarginSnapshot | None: ...
