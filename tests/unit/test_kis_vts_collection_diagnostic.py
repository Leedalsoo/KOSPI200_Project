from datetime import datetime, timezone
from pathlib import Path

import pytest

from infrastructure.kis.kis_weekday_collection_plan import CollectionPlan
from infrastructure.kis.kis_vts_collection_diagnostic import diagnose_collection


def plan():
    return CollectionPlan(
        subscriptions=(
            ("H0IOCNT0", "B016A752"),
            ("H0IFCNT0", "A01609"),
            ("H0IFASP0", "A01609"),
        ),
        monthly_expiry="2026-10-08",
        weekly_expiry="2026-09-23",
        monthly_strikes=(),
        weekly_strikes=(),
        standard_futures_symbol="A01609",
        mini_futures_symbol="A05609",
    )


def write_record(path: Path, instrument: str, tr_id: str, payload: str, seq: int):
    from infrastructure.kis.realtime_raw_store import KISRealtimeRawStore

    store = KISRealtimeRawStore(path)
    store.append(
        received_at=datetime(2026, 9, 21, 1, 0, seq, tzinfo=timezone.utc),
        trading_date="2026-09-21",
        instrument=instrument,
        tr_id=tr_id,
        payload=payload,
        sequence=seq,
    )


def test_diagnostic_reports_complete_collection(tmp_path):
    raw = tmp_path / "raw.jsonl"
    write_record(raw, "B016A752", "H0IOCNT0", "0|H0IOCNT0|3|B016A752^x^1", 1)
    write_record(raw, "A01609", "H0IFCNT0", "0|H0IFCNT0|3|A01609^x^1", 2)
    write_record(raw, "A01609", "H0IFASP0", "0|H0IFASP0|3|A01609^x^1", 3)
    log = tmp_path / "collector.log"
    log.write_text("DAY_FINISHED date=2026-09-21 record_count=3 file_sha256=abc\n", encoding="utf-8")

    report = diagnose_collection(raw, log, plan())

    assert report.expected_subscriptions == 3
    assert report.received_instruments == 2
    assert report.received_tr_ids == 3
    assert report.futures_trade == "PASS"
    assert report.futures_quote == "PASS"
    assert report.options_trade == "PASS"
    assert report.missing_contracts == ()
    assert report.reconnect_count == 0
    assert report.error_frames == 0
    assert report.hash_validation == "PASS"
    assert report.overall == "PASS"


def test_diagnostic_blocks_when_expected_contract_is_missing(tmp_path):
    raw = tmp_path / "raw.jsonl"
    write_record(raw, "A01609", "H0IFCNT0", "0|H0IFCNT0|3|A01609^x^1", 1)
    log = tmp_path / "collector.log"
    log.write_text("DAY_FINISHED date=2026-09-21 record_count=1 file_sha256=abc\n", encoding="utf-8")

    report = diagnose_collection(raw, log, plan())

    assert report.missing_contracts == (("H0IOCNT0", "B016A752"), ("H0IFASP0", "A01609"))
    assert report.overall == "FAIL"


def test_diagnostic_counts_receive_errors_as_reconnects(tmp_path):
    raw = tmp_path / "raw.jsonl"
    write_record(raw, "A01609", "H0IFCNT0", "0|H0IFCNT0|3|A01609^x^1", 1)
    log = tmp_path / "collector.log"
    log.write_text(
        "RECEIVE_ERROR date=2026-09-21 error=socket lost\n"
        "RECEIVE_ERROR date=2026-09-21 error=socket lost\n",
        encoding="utf-8",
    )

    report = diagnose_collection(raw, log, plan())

    assert report.reconnect_count == 2
    assert report.overall == "FAIL"


def test_diagnostic_blocks_hash_validation_when_raw_file_missing(tmp_path):
    raw = tmp_path / "missing.jsonl"
    log = tmp_path / "collector.log"
    log.write_text("", encoding="utf-8")

    report = diagnose_collection(raw, log, plan())

    assert report.hash_validation == "BLOCKED"
    assert report.overall == "BLOCKED"


def test_diagnostic_rejects_tampered_payload(tmp_path):
    raw = tmp_path / "raw.jsonl"
    write_record(raw, "A01609", "H0IFCNT0", "0|H0IFCNT0|3|A01609^x^1", 1)
    text = raw.read_text(encoding="utf-8").replace("A01609^x^1", "A01609^x^999")
    raw.write_text(text, encoding="utf-8")
    log = tmp_path / "collector.log"
    log.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="KIS_RAW_PAYLOAD_HASH_MISMATCH_LINE:1"):
        diagnose_collection(raw, log, plan())

def test_diagnostic_writes_machine_readable_report(tmp_path):
    from infrastructure.kis.kis_vts_collection_diagnostic import write_report
    report = __import__("infrastructure.kis.kis_vts_collection_diagnostic", fromlist=["CollectionDiagnosticReport"]).CollectionDiagnosticReport(
        expected_subscriptions=3, received_instruments=2, received_tr_ids=3,
        futures_trade="PASS", futures_quote="PASS", options_trade="PASS",
        missing_contracts=(), reconnect_count=0, error_frames=0,
        hash_validation="PASS", overall="PASS",
    )
    path = write_report(report, tmp_path / "collection_report.json")
    assert path.exists()
    payload = __import__("json").loads(path.read_text(encoding="utf-8"))
    assert payload["expected_subscriptions"] == 3
    assert payload["overall"] == "PASS"
    assert payload["missing_contracts"] == []

def test_weekday_collector_can_run_daily_diagnostic(tmp_path, monkeypatch):
    from infrastructure.kis import kis_vts_weekday_collector as collector_module
    from infrastructure.kis.kis_vts_collection_diagnostic import diagnose_collection
    from infrastructure.kis.realtime_raw_store import KISRealtimeRawStore

    raw = tmp_path / "2026-09-21" / "kis_vts_raw.jsonl"
    store = KISRealtimeRawStore(raw)
    from datetime import datetime, timezone
    for seq, (tr_id, symbol) in enumerate(plan().subscriptions, 1):
        store.append(
            received_at=datetime(2026, 9, 21, 1, 0, seq, tzinfo=timezone.utc),
            trading_date="2026-09-21", instrument=symbol, tr_id=tr_id,
            payload=f"0|{tr_id}|3|{symbol}^x^1", sequence=seq,
        )
    store.write_manifest(source="KIS_VTS_WEBSOCKET_RAW", endpoint="ws://ops.koreainvestment.com:31000")
    log = tmp_path / "collector.log"
    log.write_text("DAY_FINISHED date=2026-09-21 record_count=3 file_sha256=x\n", encoding="utf-8")
    monkeypatch.setattr(collector_module, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(collector_module, "LOG_PATH", log)

    paths = collector_module.write_daily_collection_diagnostic(__import__("datetime").date(2026, 9, 21), plan())

    assert paths["json"].exists()
    assert paths["text"].exists()
