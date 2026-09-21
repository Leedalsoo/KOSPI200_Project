"""Read-only compatibility view for pre-2026-09-22 market archives."""
from __future__ import annotations

from datetime import date
from pathlib import Path


class LegacyMarketDataAdapter:
    """Expose legacy archives without copying, deleting, or overwriting them."""

    def __init__(self, data_root: str | Path):
        self.data_root = Path(data_root)

    @staticmethod
    def _date_token(value: str | date) -> str:
        return value.isoformat() if isinstance(value, date) else str(value)

    def files_for(self, trading_date: str | date) -> list[str]:
        token = self._date_token(trading_date).replace("-", "")
        result: list[str] = []
        rest_dir = self.data_root / "kis_rest_collection"
        if rest_dir.exists():
            for path in sorted(rest_dir.glob(f"{token}_*")):
                if path.is_file():
                    result.append(path.relative_to(self.data_root).as_posix())
        minute_dir = self.data_root / "kis_rest_minute_backfill"
        if minute_dir.exists():
            for path in sorted(minute_dir.glob(f"*{token}*")):
                if path.is_file():
                    result.append(path.relative_to(self.data_root).as_posix())
        for path in sorted(self.data_root.glob("historical_market_observations.jsonl*")):
            if path.is_file():
                result.append(path.relative_to(self.data_root).as_posix())
        return result
