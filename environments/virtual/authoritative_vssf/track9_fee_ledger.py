from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from contracts.track9_fee_ledger import Track9FeeLedger, Track9FeeRecord


class VirtualTrack9FeeLedger(Track9FeeLedger):
    """Authoritative Virtual execution-fee ledger for Track9 projections."""

    def __init__(self) -> None:
        self._records: dict[str, Track9FeeRecord] = {}

    def record(self, fee: Track9FeeRecord) -> None:
        existing = self._records.get(fee.execution_id)
        if existing is not None:
            if existing != fee:
                raise ValueError("TRACK9_FEE_DUPLICATE_CONFLICT")
            return
        self._records[fee.execution_id] = fee

    def query(
        self,
        *,
        run_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> tuple[Track9FeeRecord, ...]:
        rows = [row for row in self._records.values() if row.run_id == run_id]
        if start is not None:
            rows = [row for row in rows if row.executed_at >= start]
        if end is not None:
            rows = [row for row in rows if row.executed_at < end]
        return tuple(sorted(rows, key=lambda row: (row.executed_at, row.execution_id)))

    def total(
        self,
        *,
        run_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Decimal:
        return sum((row.fee_amount for row in self.query(run_id=run_id, start=start, end=end)), Decimal("0"))

    def snapshot(self, *, run_id: str) -> tuple[Track9FeeRecord, ...]:
        return self.query(run_id=run_id)
