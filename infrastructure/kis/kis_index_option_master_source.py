from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo
from urllib.request import Request, urlopen
from zipfile import ZipFile

KIS_INDEX_MASTER_URL = "https://new.real.download.dws.co.kr/common/master/fo_idx_code_mts.mst.zip"
KOSPI200_UNDERLYING = "2001"
DEFAULT_MASTER_CACHE_DIR = Path("data/reference/kis/index_master")
MASTER_CACHE_SCHEMA = "kis-index-master-snapshot-v1"
MASTER_TTL = timedelta(hours=24)

# The type code is accepted only when the human-readable label in the same
# official KIS master row corroborates the product family and call/put side.
_OPTION_TYPE_BY_CODE = {
    "5": "CALL", "6": "PUT", "D": "CALL", "E": "PUT",
    "L": "CALL", "M": "PUT", "N": "CALL", "O": "PUT",
}
_MONTHLY_CODES = {"5", "6", "D", "E"}
_THURSDAY_WEEKLY_CODES = {"L", "M"}
_MONDAY_WEEKLY_CODES = {"N", "O"}
_MINI_CODES = {"D", "E"}


class KISIndexMasterError(RuntimeError):
    pass


class KISIndexMasterUnavailable(KISIndexMasterError):
    pass


@dataclass(frozen=True)
class KISIndexMasterSnapshot:
    raw_content: str
    archive_sha256: str
    archive_path: Path
    fetched_at: datetime
    source_url: str
    row_count: int


DownloadBytes = Callable[[str], bytes]


def _now_utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("KIS_MASTER_CLOCK_MUST_BE_TIMEZONE_AWARE")
    return current.astimezone(timezone.utc)


def _decode_archive(payload: bytes) -> tuple[str, int]:
    if not payload:
        raise KISIndexMasterError("KIS_INDEX_MASTER_EMPTY_PAYLOAD")
    try:
        with ZipFile(BytesIO(payload)) as archive:
            members = [name for name in archive.namelist() if name.lower().endswith(".mst")]
            if len(members) != 1:
                raise KISIndexMasterError("KIS_INDEX_MASTER_MST_MEMBER_NOT_UNIQUE")
            raw = archive.read(members[0]).decode("cp949", errors="strict")
    except KISIndexMasterError:
        raise
    except Exception as exc:
        raise KISIndexMasterError("KIS_INDEX_MASTER_ARCHIVE_INVALID") from exc
    rows = raw.splitlines()
    if not rows or not any(len(line.split("|")) >= 9 for line in rows):
        raise KISIndexMasterError("KIS_INDEX_MASTER_NO_VALID_ROWS")
    return raw, len(rows)


def _valid_cached_snapshots(cache_dir: Path) -> list[KISIndexMasterSnapshot]:
    candidates: list[KISIndexMasterSnapshot] = []
    if not cache_dir.is_dir():
        return candidates
    for manifest_path in cache_dir.glob("fo_idx_code_mts_*.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("schema_version") != MASTER_CACHE_SCHEMA:
                continue
            if manifest.get("source_url") != KIS_INDEX_MASTER_URL:
                continue
            archive_name = manifest.get("archive_file")
            if not isinstance(archive_name, str) or Path(archive_name).name != archive_name:
                continue
            archive_path = cache_dir / archive_name
            payload = archive_path.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            if digest != manifest.get("archive_sha256"):
                continue
            raw, row_count = _decode_archive(payload)
            if row_count != manifest.get("row_count"):
                continue
            fetched_at = datetime.fromisoformat(str(manifest["fetched_at_utc"]))
            if fetched_at.tzinfo is None:
                continue
            candidates.append(KISIndexMasterSnapshot(
                raw_content=raw,
                archive_sha256=digest,
                archive_path=archive_path,
                fetched_at=fetched_at.astimezone(timezone.utc),
                source_url=KIS_INDEX_MASTER_URL,
                row_count=row_count,
            ))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, KISIndexMasterError):
            continue
    return sorted(candidates, key=lambda item: (item.fetched_at, item.archive_path.name), reverse=True)


def _write_snapshot(
    payload: bytes,
    cache_dir: Path,
    *,
    fetched_at: datetime,
    source_url: str = KIS_INDEX_MASTER_URL,
) -> KISIndexMasterSnapshot:
    raw, row_count = _decode_archive(payload)
    digest = hashlib.sha256(payload).hexdigest()
    market_date = fetched_at.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
    stamp = market_date
    stem = f"fo_idx_code_mts_{stamp}_{digest[:8]}"
    archive_path = cache_dir / f"{stem}.zip"
    manifest_path = cache_dir / f"{stem}.json"
    cache_dir.mkdir(parents=True, exist_ok=True)
    if archive_path.exists():
        if hashlib.sha256(archive_path.read_bytes()).hexdigest() != digest:
            raise KISIndexMasterError("KIS_MASTER_APPEND_ONLY_FILENAME_COLLISION")
    else:
        with archive_path.open("xb") as target:
            target.write(payload)
    manifest = {
        "schema_version": MASTER_CACHE_SCHEMA,
        "source_url": source_url,
        "fetched_at_utc": fetched_at.isoformat(),
        "market_date_kst": market_date,
        "archive_file": archive_path.name,
        "archive_sha256": digest,
        "row_count": row_count,
        "encoding": "cp949",
        "append_only": True,
    }
    encoded = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if manifest_path.exists():
        if manifest_path.read_bytes() != encoded:
            raise KISIndexMasterError("KIS_MASTER_APPEND_ONLY_MANIFEST_COLLISION")
    else:
        with manifest_path.open("xb") as target:
            target.write(encoded)
    return KISIndexMasterSnapshot(
        raw_content=raw,
        archive_sha256=digest,
        archive_path=archive_path,
        fetched_at=fetched_at,
        source_url=source_url,
        row_count=row_count,
    )


def _write_refresh_attempt(cache_dir: Path, market_date: str, *, status: str, error_code: str | None = None, archive_sha256: str | None = None) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"refresh_attempt_{market_date}.json"
    record = {
        "schema_version": "kis-index-master-refresh-attempt-v1",
        "market_date_kst": market_date,
        "attempted_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "error_code": error_code,
        "archive_sha256": archive_sha256,
        "append_only": True,
    }
    encoded = (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if path.exists():
        return
    with path.open("xb") as target:
        target.write(encoded)


def get_kis_index_master_snapshot(
    *,
    cache_dir: Path | None = None,
    downloader: DownloadBytes | None = None,
    now: datetime | None = None,
    timeout: float = 15.0,
) -> KISIndexMasterSnapshot:
    cache = Path(cache_dir or DEFAULT_MASTER_CACHE_DIR)
    current = _now_utc(now)
    current_market_date = current.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
    cached = _valid_cached_snapshots(cache)
    ttl_valid = [
        item for item in cached
        if timedelta(0) <= current - item.fetched_at <= MASTER_TTL
    ]
    same_day = [
        item for item in ttl_valid
        if item.fetched_at.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d") == current_market_date
    ]
    if same_day:
        return same_day[0]

    attempt_path = cache / f"refresh_attempt_{current_market_date}.json"
    if attempt_path.exists():
        try:
            attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
            if attempt.get("status") == "FAILED":
                if ttl_valid:
                    return ttl_valid[0]
                raise KISIndexMasterUnavailable("KIS_INDEX_MASTER_REFRESH_FAILED_TODAY_TTL_EXPIRED")
            if attempt.get("status") == "SUCCESS":
                # A success record without a valid same-day snapshot is corruption; do not re-download.
                if ttl_valid:
                    return ttl_valid[0]
                raise KISIndexMasterUnavailable("KIS_INDEX_MASTER_SUCCESS_RECORD_WITHOUT_VALID_SNAPSHOT")
        except KISIndexMasterUnavailable:
            raise
        except Exception as exc:
            if ttl_valid:
                return ttl_valid[0]
            raise KISIndexMasterUnavailable("KIS_INDEX_MASTER_REFRESH_ATTEMPT_RECORD_INVALID") from exc

    try:
        if downloader is not None:
            payload = downloader(KIS_INDEX_MASTER_URL)
        else:
            request = Request(
                KIS_INDEX_MASTER_URL,
                headers={"User-Agent": "KOSPI200_Project/Project200"},
                method="GET",
            )
            with urlopen(request, timeout=timeout) as response:
                payload = response.read()
        snapshot = _write_snapshot(payload, cache, fetched_at=current)
        _write_refresh_attempt(
            cache, current_market_date, status="SUCCESS", archive_sha256=snapshot.archive_sha256
        )
        return snapshot
    except Exception as exc:
        try:
            _write_refresh_attempt(
                cache, current_market_date, status="FAILED", error_code=type(exc).__name__
            )
        except Exception:
            pass
        # Prior-day data is usable only while the approved 24-hour TTL remains valid.
        if ttl_valid:
            return ttl_valid[0]
        raise KISIndexMasterUnavailable("KIS_INDEX_MASTER_REFRESH_FAILED_OR_TTL_EXPIRED") from exc


def _option_row(raw_fields: list[str], snapshot: KISIndexMasterSnapshot) -> dict[str, str | Decimal | None]:
    code = raw_fields[0].strip()
    symbol = raw_fields[1].strip()
    standard_code = raw_fields[2].strip()
    name = raw_fields[3].strip()
    strike_raw = raw_fields[5].strip()
    option_type = _OPTION_TYPE_BY_CODE.get(code)
    if not symbol or not standard_code or not option_type:
        return {}
    if raw_fields[7].strip() != KOSPI200_UNDERLYING:
        return {}

    try:
        strike = Decimal(strike_raw)
    except (InvalidOperation, ValueError):
        return {}
    if strike <= 0:
        return {}

    monthly_match = re.search(r"(?<!\d)(20\d{4})(?!\d)", name)
    weekly_match = re.search(r"(?<!\d)(\d{2})(\d{2})W([1-5])(?!\d)", name, re.IGNORECASE)
    if code in _MONTHLY_CODES:
        if not monthly_match or weekly_match:
            return {}
        label_side = re.search(r"(C|P)\s+20\d{4}(?:\d{2})?(?:\s|$)", name)
        if not label_side or (label_side.group(1) == "C") != (option_type == "CALL"):
            return {}
        product_series = "MONTHLY"
        contract_month = monthly_match.group(1)
        week_label = None
        expiry_label = contract_month
    elif code in _THURSDAY_WEEKLY_CODES | _MONDAY_WEEKLY_CODES:
        if not weekly_match:
            return {}
        label_side = re.search(r"(C|P)\s+\d{4}W[1-5](?:\s|$)", name, re.IGNORECASE)
        if not label_side or (label_side.group(1).upper() == "C") != (option_type == "CALL"):
            return {}
        monday_marker = bool(re.search(r"M\s+[CP]\s+\d{4}W[1-5]", name, re.IGNORECASE))
        if code in _MONDAY_WEEKLY_CODES and not monday_marker:
            return {}
        if code in _THURSDAY_WEEKLY_CODES and monday_marker:
            return {}
        product_series = "MONDAY_WEEKLY" if code in _MONDAY_WEEKLY_CODES else "THURSDAY_WEEKLY"
        contract_month = f"20{weekly_match.group(1)}{weekly_match.group(2)}"
        week_label = f"W{weekly_match.group(3)}"
        expiry_label = f"{weekly_match.group(1)}{weekly_match.group(2)}W{weekly_match.group(3)}"
    else:
        return {}

    return {
        "short_code": symbol,
        "standard_code": standard_code,
        "type_code": code,
        "option_type": option_type,
        "product_series": product_series,
        "instrument_family": "MINI" if code in _MINI_CODES else "STANDARD",
        "month": contract_month,
        "expiry_label": expiry_label,
        "week_label": week_label,
        "strike": strike,
        "master_name": name,
        "source": "KIS_OFFICIAL_INDEX_MASTER",
        "source_url": snapshot.source_url,
        "master_fetched_at": snapshot.fetched_at.isoformat(),
        "master_sha256": snapshot.archive_sha256,
        "master_row_count": snapshot.row_count,
    }


def load_kis_index_option_rows(
    *,
    cache_dir: Path | None = None,
    downloader: DownloadBytes | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, str | Decimal | None], ...]:
    snapshot = get_kis_index_master_snapshot(cache_dir=cache_dir, downloader=downloader, now=now)
    rows: list[dict[str, str | Decimal | None]] = []
    for line in snapshot.raw_content.splitlines():
        fields = [part.strip() for part in line.split("|")]
        if len(fields) < 9:
            continue
        row = _option_row(fields, snapshot)
        if row:
            rows.append(row)
    if not rows:
        raise KISIndexMasterError("KIS_KOSPI200_OPTION_MASTER_EMPTY_OR_UNRECOGNIZED")
    return tuple(rows)


def current_kospi200_futures_symbols(
    day: date,
    *,
    cache_dir: Path | None = None,
    downloader: DownloadBytes | None = None,
    now: datetime | None = None,
) -> tuple[tuple[str, str], ...]:
    snapshot = get_kis_index_master_snapshot(cache_dir=cache_dir, downloader=downloader, now=now)
    current_month = f"{day.year:04d}{day.month:02d}"
    candidates: list[tuple[str, str, str]] = []
    for line in snapshot.raw_content.splitlines():
        fields = [part.strip() for part in line.split("|")]
        if len(fields) < 9 or fields[7] != KOSPI200_UNDERLYING:
            continue
        kind, short_code, name = fields[0], fields[1], fields[3]
        if kind not in {"1", "B"} or not short_code or not name:
            continue
        parts = name.split()
        month = parts[-2] if len(parts) >= 2 and parts[-1].startswith("(") else (parts[1] if len(parts) > 1 else "")
        if len(month) == 6 and month.isdigit() and month >= current_month:
            candidates.append((month, kind, short_code))
    result = []
    for kind in ("1", "B"):
        matches = sorted((item for item in candidates if item[1] == kind), key=lambda item: item[0])
        if not matches:
            raise KISIndexMasterError(f"KIS_KOSPI200_FUTURES_REQUIRED:{kind}:{current_month}")
        result.append(("STANDARD" if kind == "1" else "MINI", matches[0][2]))
    return tuple(result)


def current_monthly_option_symbols(
    day: date,
    reference_price: Decimal,
    offsets: tuple[Decimal, ...],
    *,
    cache_dir: Path | None = None,
    downloader: DownloadBytes | None = None,
    now: datetime | None = None,
) -> tuple[tuple[str, str], ...]:
    rows = load_kis_index_option_rows(cache_dir=cache_dir, downloader=downloader, now=now)
    current_month = f"{day.year:04d}{day.month:02d}"
    future_months = sorted({
        str(row["month"]) for row in rows
        if row["product_series"] == "MONTHLY"
        and row["instrument_family"] == "STANDARD"
        and row["type_code"] in {"5", "6"}
        and str(row["month"]) >= current_month
    })
    if not future_months:
        raise KISIndexMasterError(f"KIS_MONTHLY_OPTION_MONTH_REQUIRED:{current_month}")
    month = future_months[0]
    month_rows = [
        row for row in rows
        if row["product_series"] == "MONTHLY"
        and row["instrument_family"] == "STANDARD"
        and row["type_code"] in {"5", "6"}
        and str(row["month"]) == month
    ]
    strikes = sorted({row["strike"] for row in month_rows if isinstance(row["strike"], Decimal)})
    if not strikes:
        raise KISIndexMasterError(f"KIS_MONTHLY_OPTION_STRIKES_REQUIRED:{month}")
    atm = min(strikes, key=lambda strike: abs(strike - Decimal(reference_price)))
    result: list[tuple[str, str]] = []
    for offset in offsets:
        strike = atm + offset
        for option_type in ("PUT", "CALL"):
            matches = [
                row for row in month_rows
                if row["option_type"] == option_type and row["strike"] == strike
            ]
            if len(matches) != 1:
                raise KISIndexMasterError(f"KIS_OPTION_SYMBOL_REQUIRED:{month}:{option_type}:{strike}:{len(matches)}")
            result.append(("H0IOCNT0", str(matches[0]["short_code"])))
    return tuple(result)
