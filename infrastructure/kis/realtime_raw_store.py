from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class KISRealtimeRawStore:
    """Append-only raw KIS realtime frame store with payload provenance."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(
        self,
        *,
        received_at: datetime,
        trading_date: str,
        instrument: str,
        tr_id: str,
        payload: str,
        sequence: int | None = None,
    ) -> dict[str, Any]:
        clean_date = str(trading_date).strip()
        clean_instrument = str(instrument).strip()
        clean_tr_id = str(tr_id).strip()
        if not clean_date:
            raise ValueError("TRADING_DATE_REQUIRED")
        if not clean_instrument or not clean_tr_id:
            raise ValueError("TR_ID_AND_SYMBOL_REQUIRED")
        if not isinstance(payload, str) or not payload:
            raise ValueError("RAW_PAYLOAD_REQUIRED")
        if received_at.tzinfo is None:
            raise ValueError("RECEIVED_AT_MUST_BE_TIMEZONE_AWARE")

        record: dict[str, Any] = {
            "schema": "kis-realtime-raw-v1",
            "received_at": received_at.astimezone(timezone.utc).isoformat(),
            "trading_date": clean_date,
            "instrument": clean_instrument,
            "tr_id": clean_tr_id,
            "payload_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            "payload": payload,
        }
        if sequence is not None:
            record["sequence"] = int(sequence)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        return record

    def count(self) -> int:
        if not self.path.exists():
            return 0
        with self.path.open("r", encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())

    def records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"INVALID_KIS_RAW_RECORD_LINE:{line_number}") from exc
                if record.get("schema") != "kis-realtime-raw-v1":
                    raise ValueError(f"UNSUPPORTED_KIS_RAW_SCHEMA_LINE:{line_number}")
                if hashlib.sha256(str(record.get("payload", "")).encode("utf-8")).hexdigest() != record.get("payload_sha256"):
                    raise ValueError(f"KIS_RAW_PAYLOAD_HASH_MISMATCH_LINE:{line_number}")
                records.append(record)
        return records

    def write_manifest(self, *, source: str, endpoint: str) -> dict[str, Any]:
        clean_source = str(source).strip()
        clean_endpoint = str(endpoint).strip()
        if not clean_source:
            raise ValueError("RAW_SOURCE_REQUIRED")
        if not clean_endpoint:
            raise ValueError("RAW_ENDPOINT_REQUIRED")
        records = self.records()
        manifest_path = self.path.with_suffix(self.path.suffix + ".manifest.json")
        manifest = {
            "schema": "kis-realtime-raw-manifest-v1",
            "source": clean_source,
            "endpoint": clean_endpoint,
            "trading_date": records[0]["trading_date"] if records else None,
            "instrument": records[0]["instrument"] if records else None,
            "record_count": len(records),
            "file": str(self.path),
            "file_sha256": self.sha256(),
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest["manifest_path"] = str(manifest_path)
        return manifest

    def sha256(self) -> str:
        digest = hashlib.sha256()
        if self.path.exists():
            with self.path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        return digest.hexdigest()
