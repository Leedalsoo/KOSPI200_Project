from __future__ import annotations

from contracts.track9_margin_read_model import Track9MarginReadModel, Track9MarginSnapshot


class VSSFTrack9MarginReadModel(Track9MarginReadModel):
    """Track9 semantic projection of the authoritative VSSF account snapshot."""

    def __init__(self, account_snapshot_source) -> None:
        self._source = account_snapshot_source

    def snapshot(self, *, run_id: str) -> Track9MarginSnapshot | None:
        if not run_id.strip():
            return None
        account_id = getattr(self._source, "account_id", None)
        snapshot = self._source.snapshot()
        if snapshot is None or not getattr(snapshot, "freshness", None):
            return None
        balances = snapshot.balances
        total = balances.get("cash")
        used = balances.get("margin_used")
        free = balances.get("available_cash")
        if account_id is None or total is None or used is None or free is None:
            return None
        if total <= 0 or used < 0 or free < 0:
            return None
        try:
            return Track9MarginSnapshot(
                run_id=run_id,
                account_id=str(account_id),
                total_balance=total,
                used_margin=used,
                free_margin=free,
                observed_at=snapshot.as_of,
                source="VSSF:AccountSnapshot",
            )
        except ValueError:
            return None
