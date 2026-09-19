from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from contracts.historical_daily_store import HistoricalDailyStore
from contracts.historical_market_ohlc import HistoricalDailyOHLC
from infrastructure.kis.krx_historical_daily_normalizer import (
    KRXDailyHistoricalNormalizer,
    KRXDailyNormalizationError,
)


class KRXDailyIngestionError(ValueError):
    """Raised when actual KRX Daily ingestion cannot be proven safe."""


class KRXDailyHistoricalIngestor:
    """Normalize actual KRX Daily files and persist only unambiguous canonical records."""

    OPTION_ENDPOINT = "https://data-dbg.krx.co.kr/svc/apis/drv/opt_bydd_trd"
    FUTURES_ENDPOINT = "https://data-dbg.krx.co.kr/svc/apis/drv/fut_bydd_trd"

    def __init__(
        self,
        *,
        normalizer: KRXDailyHistoricalNormalizer,
        store: HistoricalDailyStore,
        raw_dir: str | Path,
        master_paths: Iterable[str | Path],
    ) -> None:
        self.normalizer = normalizer
        self.store = store
        self.raw_dir = Path(raw_dir)
        self.master_paths = tuple(Path(p) for p in master_paths)
        if not self.raw_dir.exists():
            raise KRXDailyIngestionError("KRX_DAILY_RAW_DIR_REQUIRED")
        if not self.master_paths or any(not p.exists() for p in self.master_paths):
            raise KRXDailyIngestionError("KRX_MARKETPLACE_MASTER_FILES_REQUIRED")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _rows(path: Path) -> list[dict[str, Any]]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = payload["OutBlock_1"]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise KRXDailyIngestionError(f"INVALID_KRX_DAILY_FILE:{path.name}") from exc
        if not isinstance(rows, list):
            raise KRXDailyIngestionError(f"INVALID_KRX_DAILY_ROWS:{path.name}")
        return rows

    @staticmethod
    def _price_complete(row: dict[str, Any]) -> bool:
        return all(str(row.get(field, "")).strip() for field in ("TDD_OPNPRC", "TDD_HGPRC", "TDD_LWPRC", "TDD_CLSPRC"))

    def _provenance(self, raw_path: Path, endpoint: str, record: HistoricalDailyOHLC) -> dict[str, str]:
        return {
            "raw_file": raw_path.name,
            "raw_sha256": self._sha256(raw_path),
            "source_endpoint": endpoint,
            "trading_date": record.trading_date.isoformat(),
            "krx_isu_cd": record.source.split("KRX_ISU_CD=", 1)[1],
            "master_files": ",".join(p.name for p in self.master_paths),
            "master_sha256": ",".join(self._sha256(p) for p in self.master_paths),
            "observation_semantics": "EOD_DAILY_OHLC;observed_at_is_date_anchor_not_trade_timestamp",
        }

    @staticmethod
    def _canonical_key(record: HistoricalDailyOHLC) -> tuple[str, str, str]:
        return record.symbol, record.trading_date.isoformat(), record.source

    def ingest_file(self, raw_path: str | Path, *, kind: str) -> tuple[int, int, dict[str, int]]:
        path = Path(raw_path)
        endpoint = self.OPTION_ENDPOINT if kind == "option" else self.FUTURES_ENDPOINT if kind == "futures" else ""
        if not endpoint:
            raise KRXDailyIngestionError("KRX_DAILY_KIND_INVALID")
        rows = self._rows(path)
        candidates: list[tuple[HistoricalDailyOHLC, dict[str, str]]] = []
        blocked = 0
        reasons: dict[str, int] = {}
        grouped: dict[tuple[str, str, str], list[tuple[HistoricalDailyOHLC, dict[str, str]]]] = defaultdict(list)
        for row in rows:
            if not self._price_complete(row):
                continue
            try:
                record = self.normalizer.normalize_option_row(row) if kind == "option" else self.normalizer.normalize_futures_row(row)
                grouped[self._canonical_key(record)].append((record, self._provenance(path, endpoint, record)))
            except KRXDailyNormalizationError as exc:
                blocked += 1
                reasons[str(exc)] = reasons.get(str(exc), 0) + 1

        for key, records in grouped.items():
            if len(records) != 1:
                blocked += len(records)
                reasons["CANONICAL_DAILY_IDENTITY_COLLISION"] = reasons.get("CANONICAL_DAILY_IDENTITY_COLLISION", 0) + len(records)
                continue
            candidates.append(records[0])

        stored = self.store.append_many(candidates)
        return stored, blocked, reasons

    def ingest_20260918(self) -> dict[str, Any]:
        options = self.raw_dir / "20260918_options_daily.json"
        futures = self.raw_dir / "20260918_futures_daily.json"
        if not options.exists() or not futures.exists():
            raise KRXDailyIngestionError("KRX_20260918_DAILY_FILES_REQUIRED")
        o = self.ingest_file(options, kind="option")
        f = self.ingest_file(futures, kind="futures")
        return {
            "options": {"stored": o[0], "blocked": o[1], "reasons": o[2]},
            "futures": {"stored": f[0], "blocked": f[1], "reasons": f[2]},
        }
