from datetime import datetime, timezone
from pathlib import Path

import pytest

from infrastructure.kis.kis_realtime_collector import KISRealtimeCollector
from infrastructure.kis.realtime_raw_store import KISRealtimeRawStore


class FakeTransport:
    def __init__(self):
        self.connected = 0
        self.closed = 0
        self.subscriptions = []
        self.frames = []
        self.fail_once = False

    async def connect(self):
        self.connected += 1

    async def subscribe(self, tr_id, symbol):
        self.subscriptions.append((tr_id, symbol))

    async def recv(self):
        if self.fail_once:
            self.fail_once = False
            raise ConnectionError("socket lost")
        return self.frames.pop(0)

    async def close(self):
        self.closed += 1


def test_raw_store_preserves_original_payload_and_hash(tmp_path):
    store = KISRealtimeRawStore(tmp_path / "20260921" / "A01609.jsonl")
    record = store.append(
        received_at=datetime(2026, 9, 21, 0, 1, 2, 345000, tzinfo=timezone.utc),
        trading_date="2026-09-21",
        instrument="A01609",
        tr_id="H0IFCNT0",
        payload="0|H0IFCNT0|3|A01609^090001^350.25",
    )

    assert record["schema"] == "kis-realtime-raw-v1"
    assert record["payload"] == "0|H0IFCNT0|3|A01609^090001^350.25"
    assert record["received_at"] == "2026-09-21T00:01:02.345000+00:00"
    assert len(record["payload_sha256"]) == 64
    assert store.count() == 1


def test_collector_records_before_canonical_adaptation(tmp_path):
    transport = FakeTransport()
    transport.frames = ["0|H0IFCNT0|3|A01609^090001^350.25"]
    store = KISRealtimeRawStore(tmp_path / "raw.jsonl")
    collector = KISRealtimeCollector(
        transport,
        store,
        clock=lambda: datetime(2026, 9, 21, 0, 1, 2, tzinfo=timezone.utc),
    )

    import asyncio
    asyncio.run(collector.start("2026-09-21", [("H0IFCNT0", "A01609")]))
    record = asyncio.run(collector.capture_one())

    assert record["instrument"] == "A01609"
    assert record["tr_id"] == "H0IFCNT0"
    assert record["payload"].startswith("0|H0IFCNT0|")
    assert transport.subscriptions == [("H0IFCNT0", "A01609")]


def test_collector_reconnects_once_and_preserves_raw_frame(tmp_path):
    transport = FakeTransport()
    transport.fail_once = True
    transport.frames = ["0|H0IFCNT0|3|A01609^090001^350.25"]
    store = KISRealtimeRawStore(tmp_path / "raw.jsonl")
    collector = KISRealtimeCollector(
        transport,
        store,
        max_reconnects=1,
        clock=lambda: datetime(2026, 9, 21, 0, 1, 2, tzinfo=timezone.utc),
    )

    import asyncio
    asyncio.run(collector.start("2026-09-21", [("H0IFCNT0", "A01609")]))
    record = asyncio.run(collector.capture_one())

    assert transport.connected == 2
    assert record["payload"] == "0|H0IFCNT0|3|A01609^090001^350.25"
    assert store.count() == 1


def test_collector_requires_subscription_contract():
    import asyncio
    collector = KISRealtimeCollector(FakeTransport(), KISRealtimeRawStore("unused.jsonl"))

    with pytest.raises(ValueError, match="TR_ID_AND_SYMBOL_REQUIRED"):
        asyncio.run(collector.start("2026-09-21", [("", "A01609")]))


def test_raw_store_writes_manifest_with_file_hash(tmp_path):
    store = KISRealtimeRawStore(tmp_path / "20260921" / "A01609.jsonl")
    store.append(
        received_at=datetime(2026, 9, 21, 0, 1, 2, tzinfo=timezone.utc),
        trading_date="2026-09-21", instrument="A01609", tr_id="H0IFCNT0",
        payload="0|H0IFCNT0|3|A01609^090001^350.25", sequence=1,
    )

    manifest = store.write_manifest(source="KIS_VTS_WEBSOCKET", endpoint="ws://ops.koreainvestment.com:31000")

    assert manifest["schema"] == "kis-realtime-raw-manifest-v1"
    assert manifest["source"] == "KIS_VTS_WEBSOCKET"
    assert manifest["endpoint"].startswith("ws://")
    assert manifest["record_count"] == 1
    assert manifest["instruments"] == ["A01609"]
    assert manifest["tr_ids"] == ["H0IFCNT0"]
    assert len(manifest["file_sha256"]) == 64
    assert Path(manifest["manifest_path"]).exists()
