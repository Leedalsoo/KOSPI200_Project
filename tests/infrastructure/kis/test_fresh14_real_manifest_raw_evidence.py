"""FRESH-14 actual 2026-10-02 manifest/raw consistency and hash verification."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DAY = ROOT / "data" / "kis_market_data_restart" / "2026-10-02"
RAW = DAY / "kis_vts_websocket_raw.jsonl"
RAW_MANIFEST = DAY / "kis_vts_websocket_raw.jsonl.manifest.json"
DAY_MANIFEST = DAY / "manifest.json"


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _line_count(path):
    count = 0
    last_byte = b""
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            count += chunk.count(b"\n")
            last_byte = chunk[-1:] or last_byte
    return count if last_byte == b"\n" else count + 1


def _classify(day_manifest, raw_manifest, raw_exists):
    day_status = str(day_manifest.get("collectors", {}).get("websocket", {}).get("status", "UNKNOWN")).upper()
    record_count = raw_manifest.get("record_count")
    mismatch = raw_exists and isinstance(record_count, int) and record_count > 0 and day_status in {"NOT_STARTED", "STOPPED", "UNKNOWN"}
    return "MANIFEST_RAW_LIFECYCLE_MISMATCH" if mismatch else "CONSISTENT_OR_INSUFFICIENT_EVIDENCE"


def test_fresh14_real_20261002_manifest_lifecycle_mismatch_and_raw_sha256():
    assert DAY_MANIFEST.is_file() and RAW_MANIFEST.is_file() and RAW.is_file(), "actual evidence files unavailable"
    day_manifest = json.loads(DAY_MANIFEST.read_text(encoding="utf-8-sig"))
    raw_manifest = json.loads(RAW_MANIFEST.read_text(encoding="utf-8-sig"))
    assert day_manifest.get("trading_date") == "2026-10-02"
    assert raw_manifest.get("trading_date") == "2026-10-02"
    assert day_manifest.get("collectors", {}).get("websocket", {}).get("status") == "NOT_STARTED"
    assert raw_manifest.get("record_count") == 87741
    assert _line_count(RAW) == raw_manifest.get("record_count"), "actual JSONL line count differs from raw manifest"
    assert {"H0IFCNT0", "H0IOASP0", "H0IOCNT0", "H0UPCNT0"} <= set(raw_manifest.get("tr_ids", []))
    classification = _classify(day_manifest, raw_manifest, RAW.is_file())
    assert classification == "MANIFEST_RAW_LIFECYCLE_MISMATCH"

    actual_hash = _sha256(RAW)
    assert actual_hash == raw_manifest.get("file_sha256"), "raw content hash differs from raw manifest"
    daily_file_entry = next((item for item in day_manifest.get("files", []) if item.get("path") == RAW.name), None)
    assert daily_file_entry is not None, "daily manifest has no raw file hash entry"
    assert actual_hash == daily_file_entry.get("sha256"), "raw content hash differs from daily manifest"

    # Hash consistency verifies bytes against recorded metadata, not official WS capability or ACK history.
