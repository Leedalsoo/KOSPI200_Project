from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from infrastructure.kis.kis_weekday_collection_plan import CollectionPlan, FUTURES_QUOTE_TR_ID, FUTURES_TRADE_TR_ID, OPTION_TRADE_TR_ID
from infrastructure.kis.realtime_raw_store import KISRealtimeRawStore


@dataclass(frozen=True)
class CollectionDiagnosticReport:
    expected_subscriptions: int
    received_instruments: int
    received_tr_ids: int
    futures_trade: str
    futures_quote: str
    options_trade: str
    missing_contracts: tuple[tuple[str, str], ...]
    reconnect_count: int
    error_frames: int
    hash_validation: str
    overall: str


def _status(ok: bool, *, blocked: bool = False) -> str:
    if blocked:
        return "BLOCKED"
    return "PASS" if ok else "FAIL"


def _count_reconnects(log_path: Path) -> int:
    if not log_path.exists():
        return 0
    return sum(1 for line in log_path.read_text(encoding="utf-8").splitlines() if "RECEIVE_ERROR" in line)


def _count_error_frames(records: list[dict]) -> int:
    # Do not infer an undocumented KIS error-frame schema. Count only an
    # explicitly verified marker if a future adapter records one.
    return sum(1 for record in records if str(record.get("tr_id", "")).strip() == "ERROR_FRAME")


def _validate_manifest(raw_path: Path, records: list[dict]) -> str:
    manifest_path = raw_path.with_suffix(raw_path.suffix + ".manifest.json")
    if not manifest_path.exists():
        return "PASS" if raw_path.exists() else "BLOCKED"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "FAIL"
    if manifest.get("schema") != "kis-realtime-raw-manifest-v1":
        return "FAIL"
    if manifest.get("record_count") != len(records):
        return "FAIL"
    if hashlib.sha256(raw_path.read_bytes()).hexdigest() != manifest.get("file_sha256"):
        return "FAIL"
    if sorted({str(r["instrument"]) for r in records}) != sorted(manifest.get("instruments", [])):
        return "FAIL"
    if sorted({str(r["tr_id"]) for r in records}) != sorted(manifest.get("tr_ids", [])):
        return "FAIL"
    return "PASS"


def diagnose_collection(raw_path: str | Path, log_path: str | Path, plan: CollectionPlan) -> CollectionDiagnosticReport:
    raw = Path(raw_path)
    log = Path(log_path)
    if not raw.exists():
        return CollectionDiagnosticReport(
            expected_subscriptions=len(plan.subscriptions), received_instruments=0, received_tr_ids=0,
            futures_trade="BLOCKED", futures_quote="BLOCKED", options_trade="BLOCKED",
            missing_contracts=tuple(plan.subscriptions), reconnect_count=_count_reconnects(log),
            error_frames=0, hash_validation="BLOCKED", overall="BLOCKED",
        )

    records = KISRealtimeRawStore(raw).records()
    received_pairs = {(str(r["tr_id"]), str(r["instrument"])) for r in records}
    missing = tuple(subscription for subscription in plan.subscriptions if subscription not in received_pairs)
    tr_ids = {str(r["tr_id"]) for r in records}
    instruments = {str(r["instrument"]) for r in records}
    futures_trade_symbols = {symbol for tr_id, symbol in plan.subscriptions if tr_id == FUTURES_TRADE_TR_ID}
    futures_quote_symbols = {symbol for tr_id, symbol in plan.subscriptions if tr_id == FUTURES_QUOTE_TR_ID}
    option_symbols = {symbol for tr_id, symbol in plan.subscriptions if tr_id == OPTION_TRADE_TR_ID}
    futures_trade_ok = bool(futures_trade_symbols) and all((FUTURES_TRADE_TR_ID, symbol) in received_pairs for symbol in futures_trade_symbols)
    futures_quote_ok = bool(futures_quote_symbols) and all((FUTURES_QUOTE_TR_ID, symbol) in received_pairs for symbol in futures_quote_symbols)
    options_trade_ok = bool(option_symbols) and all((OPTION_TRADE_TR_ID, symbol) in received_pairs for symbol in option_symbols)
    reconnect_count = _count_reconnects(log)
    error_frames = _count_error_frames(records)
    hash_validation = _validate_manifest(raw, records)
    statuses = [_status(futures_trade_ok), _status(futures_quote_ok), _status(options_trade_ok), _status(not missing), _status(reconnect_count == 0), _status(error_frames == 0), hash_validation]
    overall = "PASS" if all(status == "PASS" for status in statuses) else "FAIL"
    if hash_validation == "BLOCKED":
        overall = "BLOCKED"
    return CollectionDiagnosticReport(
        expected_subscriptions=len(plan.subscriptions), received_instruments=len(instruments), received_tr_ids=len(tr_ids),
        futures_trade=_status(futures_trade_ok), futures_quote=_status(futures_quote_ok), options_trade=_status(options_trade_ok),
        missing_contracts=missing, reconnect_count=reconnect_count, error_frames=error_frames,
        hash_validation=hash_validation, overall=overall,
    )


def write_report(report: CollectionDiagnosticReport, path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "expected_subscriptions": report.expected_subscriptions,
        "received_instruments": report.received_instruments,
        "received_tr_ids": report.received_tr_ids,
        "futures_trade": report.futures_trade,
        "futures_quote": report.futures_quote,
        "options_trade": report.options_trade,
        "missing_contracts": [list(item) for item in report.missing_contracts],
        "reconnect_count": report.reconnect_count,
        "error_frames": report.error_frames,
        "hash_validation": report.hash_validation,
        "overall": report.overall,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def format_report(report: CollectionDiagnosticReport) -> str:
    missing = ", ".join(f"{tr_id}:{symbol}" for tr_id, symbol in report.missing_contracts) or "0"
    return "\n".join((
        "Collection Report",
        "────────────────────────────",
        f"Expected subscriptions     {report.expected_subscriptions}",
        f"Received instruments       {report.received_instruments}",
        f"Received TR IDs            {report.received_tr_ids}",
        "",
        f"Futures trade              {report.futures_trade}",
        f"Futures quote              {report.futures_quote}",
        f"Options trade              {report.options_trade}",
        "",
        f"Missing contracts          {missing}",
        f"Reconnect count             {report.reconnect_count}",
        f"Error frames                {report.error_frames}",
        f"Hash validation             {report.hash_validation}",
        "",
        f"Overall                     {report.overall}",
    ))


def write_human_report(report: CollectionDiagnosticReport, path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(format_report(report) + "\n", encoding="utf-8")
    return output
