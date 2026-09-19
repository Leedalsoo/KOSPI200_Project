from __future__ import annotations

import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Iterator

from contracts.historical_market_ohlc import HistoricalDailyOHLC


class HistoricalDailyStore:
    """Append-only JSONL store for authoritative daily OHLC records."""

    SCHEMA = "historical-daily-ohlc-v1"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @staticmethod
    def _serialize(record: HistoricalDailyOHLC) -> dict:
        data = asdict(record)
        data["trading_date"] = record.trading_date.isoformat()
        data["observed_at"] = record.observed_at.isoformat()
        for field in ("open", "high", "low", "close"):
            data[field] = str(getattr(record, field))
        return data

    @staticmethod
    def _deserialize(data: dict) -> HistoricalDailyOHLC:
        from datetime import date, datetime
        return HistoricalDailyOHLC(
            symbol=str(data["symbol"]),
            trading_date=date.fromisoformat(data["trading_date"]),
            open=Decimal(str(data["open"])),
            high=Decimal(str(data["high"])),
            low=Decimal(str(data["low"])),
            close=Decimal(str(data["close"])),
            observed_at=datetime.fromisoformat(data["observed_at"]),
            source=str(data["source"]),
        )

    @staticmethod
    def _key(record: HistoricalDailyOHLC) -> tuple[str, str, str]:
        return record.symbol, record.trading_date.isoformat(), record.source

    def append(self, record: HistoricalDailyOHLC, *, provenance: dict[str, str]) -> None:
        if not provenance:
            raise ValueError("HISTORICAL_DAILY_PROVENANCE_REQUIRED")
        if any(not str(k).strip() or not str(v).strip() for k, v in provenance.items()):
            raise ValueError("HISTORICAL_DAILY_PROVENANCE_INVALID")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        envelope = {"schema": self.SCHEMA, "provenance": dict(provenance), "record": self._serialize(record)}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")) + "\n")

    def append_many(self, records: Iterable[tuple[HistoricalDailyOHLC, dict[str, str]]]) -> int:
        pending = list(records)
        existing_keys = {self._key(record) for record, _ in self.load_records()}
        if not pending:
            return 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        added = 0
        with self.path.open("a", encoding="utf-8") as handle:
            for record, provenance in pending:
                if not provenance:
                    raise ValueError("HISTORICAL_DAILY_PROVENANCE_REQUIRED")
                if any(not str(k).strip() or not str(v).strip() for k, v in provenance.items()):
                    raise ValueError("HISTORICAL_DAILY_PROVENANCE_INVALID")
                key = self._key(record)
                if key in existing_keys:
                    continue
                envelope = {"schema": self.SCHEMA, "provenance": dict(provenance), "record": self._serialize(record)}
                handle.write(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")) + "\n")
                existing_keys.add(key)
                added += 1
        return added

    def append_unique(self, record: HistoricalDailyOHLC, *, provenance: dict[str, str]) -> bool:
        return self.append_many([(record, provenance)]) == 1

    def records(self) -> Iterator[dict]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    envelope = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"INVALID_HISTORICAL_DAILY_RECORD_LINE:{line_number}") from exc
                if envelope.get("schema") != self.SCHEMA:
                    raise ValueError(f"UNSUPPORTED_HISTORICAL_DAILY_SCHEMA_LINE:{line_number}")
                if not envelope.get("provenance"):
                    raise ValueError(f"HISTORICAL_DAILY_PROVENANCE_REQUIRED_LINE:{line_number}")
                yield envelope

    def load_records(self, *, symbol: str | None = None, trading_date: str | None = None) -> list[tuple[HistoricalDailyOHLC, dict[str, str]]]:
        result = []
        for envelope in self.records():
            data = envelope["record"]
            if symbol is not None and data["symbol"] != symbol:
                continue
            if trading_date is not None and data["trading_date"] != trading_date:
                continue
            result.append((self._deserialize(data), dict(envelope["provenance"])))
        return result
