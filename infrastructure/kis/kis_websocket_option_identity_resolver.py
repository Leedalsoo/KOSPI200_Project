from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Mapping, Sequence
from zipfile import ZipFile

from contracts.types import OptionInstrumentIdentity
from infrastructure.kis.kis_index_option_master_source import (
    KIS_INDEX_MASTER_URL,
    MASTER_CACHE_SCHEMA,
    KISIndexMasterSnapshot,
    _decode_archive,
    _option_row,
)
from infrastructure.kis.kis_option_expiry_source import (
    EXPIRY_CACHE_SCHEMA,
    KISOptionExpiryRecord,
    KISOptionExpiryResolver,
)

IDENTITY_ROW_FIELDS = (
    "short_code",
    "standard_code",
    "type_code",
    "option_type",
    "product_series",
    "instrument_family",
    "month",
    "expiry_label",
    "week_label",
    "strike",
    "master_name",
)


class KISWebSocketIdentityResolutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class KISOptionSeriesExpiryEvidence:
    """Exact KIS expiry evidence joined through identical official master rows."""

    symbol: str
    expiry_yyyymmdd: str
    environment: str
    source: str
    endpoint: str
    tr_id: str
    received_at_utc: str
    raw_response_sha256: str
    master_sha256: str
    response_field: str = "output1.futs_last_tr_date"
    http_status: int = 200
    rt_cd: str = "0"
    target_master_sha256: str = ""
    series_key: tuple[str, str, str, str] = ()
    evidence_symbols: tuple[str, ...] = ()
    evidence_master_hashes: tuple[str, ...] = ()
    evidence_set_sha256: str = ""


def _read_snapshot_manifest(manifest_path: Path, *, expected_hash: str | None = None) -> KISIndexMasterSnapshot:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != MASTER_CACHE_SCHEMA:
            raise KISWebSocketIdentityResolutionError("KIS_MASTER_SNAPSHOT_SCHEMA_INVALID")
        if manifest.get("source_url") != KIS_INDEX_MASTER_URL:
            raise KISWebSocketIdentityResolutionError("KIS_MASTER_SNAPSHOT_SOURCE_INVALID")
        archive_name = manifest.get("archive_file")
        if not isinstance(archive_name, str) or Path(archive_name).name != archive_name:
            raise KISWebSocketIdentityResolutionError("KIS_MASTER_SNAPSHOT_ARCHIVE_NAME_INVALID")
        archive_path = manifest_path.parent / archive_name
        payload = archive_path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != manifest.get("archive_sha256") or (expected_hash and digest != expected_hash):
            raise KISWebSocketIdentityResolutionError("KIS_MASTER_SNAPSHOT_HASH_MISMATCH")
        raw_content, row_count = _decode_archive(payload)
        if row_count != manifest.get("row_count"):
            raise KISWebSocketIdentityResolutionError("KIS_MASTER_SNAPSHOT_ROW_COUNT_MISMATCH")
        fetched_at = datetime.fromisoformat(str(manifest["fetched_at_utc"]))
        if fetched_at.tzinfo is None:
            raise KISWebSocketIdentityResolutionError("KIS_MASTER_SNAPSHOT_TIMESTAMP_INVALID")
        return KISIndexMasterSnapshot(
            raw_content=raw_content,
            archive_sha256=digest,
            archive_path=archive_path,
            fetched_at=fetched_at.astimezone(timezone.utc),
            source_url=KIS_INDEX_MASTER_URL,
            row_count=row_count,
        )
    except KISWebSocketIdentityResolutionError:
        raise
    except Exception as exc:
        raise KISWebSocketIdentityResolutionError("KIS_MASTER_SNAPSHOT_INVALID") from exc


def load_kis_master_snapshot_for_date(day: date, *, cache_dir: Path) -> KISIndexMasterSnapshot:
    """Load only the verified official KIS snapshot for the requested market date."""
    market_date = day.strftime("%Y%m%d")
    manifests: list[tuple[datetime, Path]] = []
    for path in cache_dir.glob(f"fo_idx_code_mts_{market_date}_*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            fetched_at = datetime.fromisoformat(str(payload["fetched_at_utc"]))
            if fetched_at.tzinfo is not None and payload.get("market_date_kst") == market_date:
                manifests.append((fetched_at.astimezone(timezone.utc), path))
        except Exception:
            continue
    if not manifests:
        raise KISWebSocketIdentityResolutionError(f"KIS_MASTER_SNAPSHOT_FOR_DATE_MISSING:{market_date}")
    manifests.sort(key=lambda item: item[0], reverse=True)
    return _read_snapshot_manifest(manifests[0][1])


def load_kis_master_snapshot_by_hash(master_sha256: str, *, cache_dir: Path) -> KISIndexMasterSnapshot:
    """Load a verified KIS snapshot by its exact archive hash."""
    matches: list[tuple[datetime, Path]] = []
    for path in cache_dir.glob("fo_idx_code_mts_*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("archive_sha256") != master_sha256:
                continue
            fetched_at = datetime.fromisoformat(str(payload["fetched_at_utc"]))
            if fetched_at.tzinfo is not None:
                matches.append((fetched_at.astimezone(timezone.utc), path))
        except Exception:
            continue
    if not matches:
        raise KISWebSocketIdentityResolutionError(f"KIS_MASTER_SNAPSHOT_FOR_HASH_MISSING:{master_sha256}")
    matches.sort(key=lambda item: item[0], reverse=True)
    return _read_snapshot_manifest(matches[0][1], expected_hash=master_sha256)


def rows_from_snapshot(snapshot: KISIndexMasterSnapshot) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for line in snapshot.raw_content.splitlines():
        fields = [part.strip() for part in line.split("|")]
        if len(fields) < 9:
            continue
        row = _option_row(fields, snapshot)
        if row:
            rows.append(row)
    if not rows:
        raise KISWebSocketIdentityResolutionError("KIS_OPTION_MASTER_ROWS_EMPTY")
    return tuple(rows)


def _series_key(row: Mapping[str, object]) -> tuple[str, str, str, str]:
    return (
        str(row.get("product_series") or ""),
        str(row.get("instrument_family") or ""),
        str(row.get("month") or ""),
        str(row.get("week_label") or ""),
    )


def _identity_row_equal(left: Mapping[str, object], right: Mapping[str, object]) -> bool:
    for field in IDENTITY_ROW_FIELDS:
        a, b = left.get(field), right.get(field)
        if field == "strike":
            if a is None or b is None:
                if a is not b:
                    return False
            elif Decimal(str(a)) != Decimal(str(b)):
                return False
        elif str(a or "") != str(b or ""):
            return False
    return True


def _load_expiry_records_for_all_master_hashes(cache_dir: Path) -> tuple[dict[str, KISIndexMasterSnapshot], tuple[KISOptionExpiryRecord, ...]]:
    hashes: set[str] = set()
    for path in cache_dir.glob("expiry_*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("schema_version") == EXPIRY_CACHE_SCHEMA:
                value = str(payload.get("master_sha256") or "")
                if re.fullmatch(r"[0-9a-f]{64}", value):
                    hashes.add(value)
        except Exception:
            continue
    snapshots: dict[str, KISIndexMasterSnapshot] = {}
    records: list[KISOptionExpiryRecord] = []
    for master_hash in sorted(hashes):
        snapshot = load_kis_master_snapshot_by_hash(master_hash, cache_dir=cache_dir.parent / "index_master")
        resolver = KISOptionExpiryResolver(
            master_sha256=master_hash,
            environment="VTS",
            cache_dir=cache_dir,
        )
        current = resolver.cached_records_for_current_master()
        if current:
            snapshots[master_hash] = snapshot
            records.extend(current)
    return snapshots, tuple(records)


class KISWebSocketOptionIdentityResolver:
    """Resolve exact option identity from KIS master rows plus verified KIS expiry evidence.

    Expiry evidence may come from an older/newer official KIS snapshot only when the
    contract's identity fields match exactly between the evidence snapshot and target
    snapshot. The target and evidence master hashes remain separately observable.
    """

    def __init__(
        self,
        *,
        target_snapshot: KISIndexMasterSnapshot,
        target_rows: Sequence[Mapping[str, object]],
        evidence_snapshots: Mapping[str, KISIndexMasterSnapshot],
        expiry_records: Sequence[KISOptionExpiryRecord],
    ) -> None:
        self.target_snapshot = target_snapshot
        self._target_rows: dict[str, Mapping[str, object]] = {}
        for row in target_rows:
            symbol = str(row.get("short_code") or "").strip()
            if not symbol:
                continue
            if str(row.get("master_sha256") or "") != target_snapshot.archive_sha256:
                raise KISWebSocketIdentityResolutionError("TARGET_MASTER_ROW_HASH_MISMATCH")
            existing = self._target_rows.get(symbol)
            if existing is not None and not _identity_row_equal(existing, row):
                raise KISWebSocketIdentityResolutionError(f"KIS_MASTER_DUPLICATE_SYMBOL_CONFLICT:{symbol}")
            self._target_rows[symbol] = row

        evidence_rows_by_hash = {
            master_hash: {
                str(row.get("short_code") or "").strip(): row
                for row in rows_from_snapshot(snapshot)
            }
            for master_hash, snapshot in evidence_snapshots.items()
        }
        grouped: dict[tuple[str, str, str, str], list[KISOptionExpiryRecord]] = {}
        for record in expiry_records:
            if record.environment != "VTS" or record.source != "KIS_REST:futs_last_tr_date":
                continue
            if record.master_sha256 not in evidence_rows_by_hash:
                continue
            evidence_row = evidence_rows_by_hash[record.master_sha256].get(record.symbol)
            target_row = self._target_rows.get(record.symbol)
            if evidence_row is None or target_row is None:
                continue
            if not _identity_row_equal(evidence_row, target_row):
                continue
            grouped.setdefault(_series_key(target_row), []).append(record)

        self._series_records: dict[tuple[str, str, str, str], tuple[KISOptionExpiryRecord, ...]] = {}
        for key, records in grouped.items():
            expiries = {record.expiry_yyyymmdd for record in records}
            if len(expiries) != 1:
                raise KISWebSocketIdentityResolutionError(
                    f"KIS_OPTION_SERIES_EXPIRY_CONFLICT:{key}:{sorted(expiries)}"
                )
            self._series_records[key] = tuple(sorted(records, key=lambda item: (item.symbol, item.received_at_utc)))

        self._series_evidence_sha256: dict[tuple[str, str, str, str], str] = {}
        for key, records in self._series_records.items():
            material = "\n".join(
                f"{record.symbol}|{record.expiry_yyyymmdd}|{record.master_sha256}|{record.raw_response_sha256}"
                for record in records
            )
            self._series_evidence_sha256[key] = hashlib.sha256(material.encode("utf-8")).hexdigest()

    @classmethod
    def for_trading_date(cls, day: date, *, project_root: Path) -> "KISWebSocketOptionIdentityResolver":
        master_cache = project_root / "data" / "reference" / "kis" / "index_master"
        expiry_cache = project_root / "data" / "reference" / "kis" / "option_expiry"
        target_snapshot = load_kis_master_snapshot_for_date(day, cache_dir=master_cache)
        target_rows = rows_from_snapshot(target_snapshot)
        evidence_snapshots, expiry_records = _load_expiry_records_for_all_master_hashes(expiry_cache)
        return cls(
            target_snapshot=target_snapshot,
            target_rows=target_rows,
            evidence_snapshots=evidence_snapshots,
            expiry_records=expiry_records,
        )

    def get_contract_identity(self, symbol: str) -> OptionInstrumentIdentity | None:
        clean_symbol = str(symbol).strip()
        row = self._target_rows.get(clean_symbol)
        if row is None:
            return None
        records = self._series_records.get(_series_key(row))
        if not records:
            return None
        expiry = records[0].expiry_yyyymmdd
        return OptionInstrumentIdentity(
            instrument_id=clean_symbol,
            symbol=clean_symbol,
            expiry=expiry,
            option_type=str(row["option_type"]),
            strike=Decimal(str(row["strike"])),
            contract_multiplier=None,
            identity_source="KIS_OFFICIAL_INDEX_MASTER+KIS_REST_SERIES_EXPIRY_EXACT_ROW_JOIN",
        )

    def get_expiry_record(self, symbol: str) -> KISOptionSeriesExpiryEvidence | None:
        clean_symbol = str(symbol).strip()
        row = self._target_rows.get(clean_symbol)
        if row is None:
            return None
        key = _series_key(row)
        records = self._series_records.get(key)
        if not records:
            return None
        primary = max(records, key=lambda item: item.received_at_utc)
        return KISOptionSeriesExpiryEvidence(
            symbol=clean_symbol,
            expiry_yyyymmdd=primary.expiry_yyyymmdd,
            environment="VTS",
            source="KIS_REST:futs_last_tr_date:KIS_MASTER_EXACT_ROW_SERIES_JOIN",
            endpoint=primary.endpoint,
            tr_id=primary.tr_id,
            received_at_utc=max(item.received_at_utc for item in records),
            raw_response_sha256=primary.raw_response_sha256,
            master_sha256=primary.master_sha256,
            target_master_sha256=self.target_snapshot.archive_sha256,
            series_key=key,
            evidence_symbols=tuple(item.symbol for item in records),
            evidence_master_hashes=tuple(sorted({item.master_sha256 for item in records})),
            evidence_set_sha256=self._series_evidence_sha256[key],
        )

    def provenance_metadata(self, symbol: str) -> tuple[tuple[str, str], ...]:
        record = self.get_expiry_record(symbol)
        if record is None:
            return (("master_snapshot_sha256", self.target_snapshot.archive_sha256),)
        return (
            ("master_snapshot_sha256", self.target_snapshot.archive_sha256),
            ("expiry_evidence_master_hashes", ",".join(record.evidence_master_hashes)),
            ("expiry_resolution_method", "KIS_MASTER_EXACT_ROW_SERIES_JOIN"),
            ("expiry_evidence_symbol_count", str(len(record.evidence_symbols))),
            ("expiry_evidence_set_sha256", record.evidence_set_sha256),
        )

    def summary(self, symbols: Sequence[str] | None = None) -> dict[str, object]:
        candidates = tuple(symbols) if symbols is not None else tuple(self._target_rows)
        resolved = sorted(symbol for symbol in candidates if self.get_contract_identity(symbol) is not None)
        unresolved = sorted(set(candidates) - set(resolved))
        return {
            "target_master_sha256": self.target_snapshot.archive_sha256,
            "target_master_fetched_at": self.target_snapshot.fetched_at.isoformat(),
            "candidate_symbols": len(candidates),
            "resolved_symbols": len(resolved),
            "unresolved_symbols": len(unresolved),
            "resolved_symbol_sample": resolved[:20],
            "unresolved_symbol_sample": unresolved[:20],
            "resolved_series": [
                {
                    "series_key": key,
                    "expiry_yyyymmdd": records[0].expiry_yyyymmdd,
                    "evidence_symbols": [record.symbol for record in records],
                    "evidence_master_hashes": sorted({record.master_sha256 for record in records}),
                    "evidence_set_sha256": self._series_evidence_sha256[key],
                }
                for key, records in sorted(self._series_records.items())
            ],
        }
