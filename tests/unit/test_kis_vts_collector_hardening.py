import asyncio
from datetime import date, datetime, time, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from infrastructure.kis.realtime_raw_store import KISRealtimeRawStore
from infrastructure.kis import kis_vts_weekday_collector as collector_module


def _append(store: KISRealtimeRawStore, instrument: str, tr_id: str, payload: str, seq: int) -> None:
    store.append(
        received_at=datetime(2026, 9, 21, 1, 0, seq, tzinfo=timezone.utc),
        trading_date="2026-09-21", instrument=instrument, tr_id=tr_id,
        payload=payload, sequence=seq,
    )


def test_manifest_streams_without_loading_records(monkeypatch, tmp_path):
    store = KISRealtimeRawStore(tmp_path / "raw.jsonl")
    _append(store, "A01609", "H0IFCNT0", "0|H0IFCNT0|3|A01609^x^1", 1)
    _append(store, "B016A752", "H0IOCNT0", "0|H0IOCNT0|3|B016A752^x^2", 2)
    monkeypatch.setattr(store, "records", lambda: pytest.fail("records() must not be called"))
    manifest = store.write_manifest(source="KIS_VTS_WEBSOCKET_RAW", endpoint="ws://ops.koreainvestment.com:31000")
    assert manifest["record_count"] == 2
    assert manifest["trading_date"] == "2026-09-21"
    assert manifest["instrument"] == "A01609"
    assert manifest["instruments"] == ["A01609", "B016A752"]
    assert manifest["tr_ids"] == ["H0IFCNT0", "H0IOCNT0"]


def test_truncated_tail_fails_closed_by_default(tmp_path):
    path = tmp_path / "raw.jsonl"
    store = KISRealtimeRawStore(path)
    _append(store, "A01609", "H0IFCNT0", "0|H0IFCNT0|3|A01609^x^1", 1)
    tail = '{"schema":"kis-realtime-raw-v1"'
    path.write_text(path.read_text(encoding="utf-8") + tail, encoding="utf-8")
    with pytest.raises(ValueError, match="INVALID_KIS_RAW_RECORD_LINE:2"):
        store.records()


def test_truncated_tail_can_be_tolerated_and_preserved(tmp_path):
    path = tmp_path / "raw.jsonl"
    store = KISRealtimeRawStore(path)
    _append(store, "A01609", "H0IFCNT0", "0|H0IFCNT0|3|A01609^x^1", 1)
    tail = '{"schema":"kis-realtime-raw-v1"'
    path.write_text(path.read_text(encoding="utf-8") + tail, encoding="utf-8")
    records = store.records(tolerate_truncated_tail=True)
    assert len(records) == 1
    assert path.with_name(path.name + ".truncated_tail").read_text(encoding="utf-8") == tail


def test_non_tail_corruption_fails_in_tolerant_mode(tmp_path):
    path = tmp_path / "raw.jsonl"
    store = KISRealtimeRawStore(path)
    valid = store.append(
        received_at=datetime(2026, 9, 21, 1, 0, tzinfo=timezone.utc),
        trading_date="2026-09-21", instrument="A01609", tr_id="H0IFCNT0",
        payload="0|H0IFCNT0|3|A01609^x^1", sequence=1,
    )
    del valid
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    path.write_text(lines[0] + '{"schema":"kis-realtime-raw-v1"\n' + lines[0], encoding="utf-8")
    with pytest.raises(ValueError, match="INVALID_KIS_RAW_RECORD_LINE:2"):
        store.records(tolerate_truncated_tail=True)


def test_supervisor_retries_collect_day_with_exponential_backoff(monkeypatch):
    calls = []
    sleeps = []
    outcomes = iter([RuntimeError("temporary"), None])

    async def fake_collect(day, plan):
        calls.append(day)
        outcome = next(outcomes)
        if outcome:
            raise outcome

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    times = iter([
        datetime(2026, 9, 21, 8, 31, tzinfo=collector_module.KST),
        datetime(2026, 9, 21, 8, 31, tzinfo=collector_module.KST),
        datetime(2026, 9, 24, 0, 0, tzinfo=collector_module.KST),
    ])
    monkeypatch.setattr(collector_module, "_collect_day", fake_collect)
    monkeypatch.setattr(collector_module, "build_plan", lambda: SimpleNamespace(subscriptions=()))
    monkeypatch.setattr(collector_module, "_now_kst", lambda: next(times))
    monkeypatch.setattr(collector_module.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(collector_module, "configure_logging", lambda: None)
    monkeypatch.setattr(collector_module.LOGGER, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(collector_module.LOGGER, "exception", lambda *args, **kwargs: None)
    asyncio.run(collector_module.run())
    assert len(calls) == 2
    assert sleeps == [collector_module.RESTART_BACKOFF_INITIAL_SECONDS]


def test_backoff_caps_at_sixty_seconds():
    assert collector_module._next_backoff(2) == 4
    assert collector_module._next_backoff(32) == 60
    assert collector_module._next_backoff(60) == 60


def test_start_failure_bubbles_to_supervisor_boundary(monkeypatch):
    calls = []

    async def fake_collect(day, plan):
        calls.append(day)
        raise RuntimeError("collector.start failed")

    async def fake_sleep(seconds):
        raise AssertionError("sleep should be patched only after boundary is exercised")

    times = iter([
        datetime(2026, 9, 21, 8, 31, tzinfo=collector_module.KST),
        datetime(2026, 9, 24, 0, 0, tzinfo=collector_module.KST),
    ])
    monkeypatch.setattr(collector_module, "_collect_day", fake_collect)
    monkeypatch.setattr(collector_module, "build_plan", lambda: SimpleNamespace(subscriptions=()))
    monkeypatch.setattr(collector_module, "_now_kst", lambda: next(times))
    monkeypatch.setattr(collector_module.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(collector_module, "configure_logging", lambda: None)
    monkeypatch.setattr(collector_module.LOGGER, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(collector_module.LOGGER, "exception", lambda *args, **kwargs: None)
    # The supervisor must consume this start failure rather than terminate the process.
    with pytest.raises(AssertionError):
        asyncio.run(collector_module.run())
    assert calls == [date(2026, 9, 21)]


def test_postprocessing_failures_are_isolated(monkeypatch):
    errors = []
    monkeypatch.setattr(collector_module.LOGGER, "error", lambda *args, **kwargs: errors.append(args))
    monkeypatch.setattr(collector_module, "_raw_store_for", lambda day: (_ for _ in ()).throw(RuntimeError("store")))
    # Isolation helper is expected to exist and swallow post-processing errors.
    result = collector_module._safe_write_daily_diagnostics(date(2026, 9, 21), object())
    assert result is None
    assert errors


def test_alert_writer_creates_file_for_zero_option_frames(tmp_path):
    path = collector_module._write_option_alert(
        date(2026, 9, 21), tmp_path, {"H0IFCNT0": 4, "H0IFASP0": 4, "H0IOCNT0": 0}
    )
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "H0IOCNT0" in text
    assert "수집을 중단하지" in text


def test_backup_copies_raw_day_and_verifies_sha(tmp_path, monkeypatch):
    day_dir = tmp_path / "data" / "2026-09-21"
    day_dir.mkdir(parents=True)
    raw = day_dir / "kis_vts_raw.jsonl"
    raw.write_text("raw\n", encoding="utf-8")
    backup_root = tmp_path / "backup"
    monkeypatch.setenv("PROJECT200_BACKUP_DIR", str(backup_root))
    result = collector_module._backup_day(date(2026, 9, 21), day_dir, source_root=tmp_path / "data")
    assert result is True
    assert (backup_root / "2026-09-21" / "kis_vts_raw.jsonl").read_text(encoding="utf-8") == "raw\n"


def test_logging_uses_rotating_file_handler(monkeypatch, tmp_path):
    import logging.handlers
    monkeypatch.setattr(collector_module, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(collector_module, "LOG_PATH", tmp_path / "collector.log")
    logger = collector_module.configure_logging()
    assert any(isinstance(handler, logging.handlers.RotatingFileHandler) for handler in logger.handlers)
