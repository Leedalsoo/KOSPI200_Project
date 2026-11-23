import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from infrastructure.kis.kis_realtime_collector import KISRealtimeCollector
from infrastructure.kis.realtime_raw_store import KISRealtimeRawStore


NOW = datetime(2026, 11, 24, 3, 0, tzinfo=timezone.utc)
FRAME = "0|H0IOCNT0|1|SYNTHETIC:DERIVED_SCENARIO:TRACK4-REPLAY-FRAME"
SUBSCRIPTIONS = [("H0IOCNT0", "SYNTHETIC:DERIVED_SCENARIO:TRACK4-REPLAY-FRAME")]


def _append_valid_record(store: KISRealtimeRawStore, sequence: int = 1) -> dict:
    payload = f"0|H0IOCNT0|{sequence}|SYNTHETIC:DERIVED_SCENARIO:TRACK4-VALID"
    return store.append(
        received_at=NOW,
        trading_date="20261124",
        instrument="SYNTHETIC:DERIVED_SCENARIO:TRACK4-VALID",
        tr_id="H0IOCNT0",
        payload=payload,
        sequence=sequence,
    )


@pytest.mark.parametrize(
    "invalid_tail",
    [
        b'{"schema":"kis-realtime-raw-v1","payload":"SYNTHETIC_TRUNCATED',
        b'{"schema":"kis-realtime-raw-v1","payload":"SYNTHETIC_TRUNCATED"}\n',
        b'{"schema":"kis-realtime-raw-v1","payload":"SYNTHETIC_TRUNCATED"}\n\n',
        b'{"schema":"kis-realtime-raw-v1","payload":"SYNTHETIC_TRUNCATED"}\n   \n',
        b'{"schema":"unsupported","payload":"SYNTHETIC_BAD_SCHEMA","payload_sha256":"x"}\n',
        b'{"schema":"kis-realtime-raw-v1","payload":"SYNTHETIC_BAD_HASH","payload_sha256":"x"}\n',
        b'{"schema":"kis-realtime-raw-v1","payload":"SYNTHETIC_VALID_JSON_WITHOUT_LINE_TERMINATOR"}',
    ],
)
def test_append_rejects_invalid_or_unterminated_tail_without_mutating_raw(
    tmp_path: Path, invalid_tail: bytes
):
    path = tmp_path / "raw.jsonl"
    store = KISRealtimeRawStore(path)
    _append_valid_record(store)
    with path.open("ab") as handle:
        handle.write(invalid_tail)
    before = path.read_bytes()

    with pytest.raises(ValueError, match="RAW_STORE_APPEND_BLOCKED_BY_INVALID_TAIL"):
        _append_valid_record(store, sequence=2)

    assert path.read_bytes() == before


def test_tolerant_tail_read_and_manifest_preserve_raw_then_append_is_refused(
    tmp_path: Path,
):
    path = tmp_path / "raw.jsonl"
    store = KISRealtimeRawStore(path)
    _append_valid_record(store)
    truncated_tail = b'{"schema":"kis-realtime-raw-v1","payload":"SYNTHETIC_TRUNCATED'
    with path.open("ab") as handle:
        handle.write(truncated_tail)
    raw_before = path.read_bytes()

    records = store.records(tolerate_truncated_tail=True)
    sidecar = path.with_name(path.name + ".truncated_tail")
    manifest = store.write_manifest(
        source="SYNTHETIC:DERIVED_SCENARIO",
        endpoint="SYNTHETIC:LOCAL_FIXTURE",
        tolerate_truncated_tail=True,
    )

    assert len(records) == 1
    assert sidecar.read_bytes() == truncated_tail
    assert manifest["record_count"] == 1
    assert manifest["file_sha256"] == hashlib.sha256(raw_before).hexdigest()
    assert path.read_bytes() == raw_before
    with pytest.raises(ValueError, match="RAW_STORE_APPEND_BLOCKED_BY_INVALID_TAIL"):
        _append_valid_record(store, sequence=2)
    assert path.read_bytes() == raw_before


def test_same_frame_retry_after_observer_partial_effect_duplicates_raw_and_effect(
    tmp_path: Path,
):
    async def run() -> None:
        path = tmp_path / "observer.jsonl"
        store = KISRealtimeRawStore(path)
        effects: list[str] = []
        observer_calls = 0

        def observer(payload: str, received_at: datetime) -> None:
            nonlocal observer_calls
            observer_calls += 1
            effects.append(hashlib.sha256(payload.encode("utf-8")).hexdigest())
            if observer_calls == 1:
                raise RuntimeError("SYNTHETIC_OBSERVER_AFTER_PARTIAL_EFFECT")

        class SameFrameTransport:
            async def connect(self) -> None:
                return None

            async def subscribe(self, tr_id: str, symbol: str) -> None:
                return None

            async def recv(self) -> str:
                return FRAME

            async def close(self) -> None:
                return None

        collector = KISRealtimeCollector(
            SameFrameTransport(), store, clock=lambda: NOW, frame_observer=observer
        )
        await collector.start("20261124", SUBSCRIPTIONS)
        with pytest.raises(
            RuntimeError, match="SYNTHETIC_OBSERVER_AFTER_PARTIAL_EFFECT"
        ):
            await collector.capture_one()
        second = await collector.capture_one()

        records = store.records()
        expected_hash = hashlib.sha256(FRAME.encode("utf-8")).hexdigest()
        assert second["sequence"] == 2
        assert [record["sequence"] for record in records] == [1, 2]
        assert [record["payload_sha256"] for record in records] == [
            expected_hash,
            expected_hash,
        ]
        assert effects == [expected_hash, expected_hash]
        assert observer_calls == 2

    asyncio.run(run())


def test_tolerant_read_preserves_legacy_concatenated_tail_as_unparsed_sidecar(
    tmp_path: Path,
):
    path = tmp_path / "legacy-concatenated.jsonl"
    store = KISRealtimeRawStore(path)
    _append_valid_record(store)
    later_payload = "0|H0IOCNT0|2|SYNTHETIC:DERIVED_SCENARIO:LEGACY-APPENDED-FRAME"
    later_record = {
        "schema": "kis-realtime-raw-v1",
        "received_at": NOW.isoformat(),
        "trading_date": "20261124",
        "instrument": "SYNTHETIC:DERIVED_SCENARIO:LEGACY-APPENDED-FRAME",
        "tr_id": "H0IOCNT0",
        "payload_sha256": hashlib.sha256(later_payload.encode("utf-8")).hexdigest(),
        "payload": later_payload,
        "sequence": 2,
    }
    legacy_tail = (
        b'{"schema":"kis-realtime-raw-v1","payload":"SYNTHETIC_TRUNCATED'
        + json.dumps(later_record, separators=(",", ":")).encode("utf-8")
        + b"\n"
    )
    with path.open("ab") as handle:
        handle.write(legacy_tail)
    raw_before = path.read_bytes()

    records = store.records(tolerate_truncated_tail=True)
    sidecar = path.with_name(path.name + ".truncated_tail")
    manifest = store.write_manifest(
        source="SYNTHETIC:DERIVED_SCENARIO",
        endpoint="SYNTHETIC:LEGACY_FIXTURE",
        tolerate_truncated_tail=True,
    )

    assert [record["sequence"] for record in records] == [1]
    assert sidecar.read_text(encoding="utf-8") == legacy_tail.decode("utf-8")
    assert manifest["record_count"] == 1
    assert manifest["file_sha256"] == hashlib.sha256(raw_before).hexdigest()
    assert path.read_bytes() == raw_before


@pytest.mark.parametrize(
    ("invalid_middle", "expected_error"),
    [
        (b"{SYNTHETIC_MALFORMED_INTERIOR}\n", "INVALID_KIS_RAW_RECORD_LINE:2"),
        (
            b'{"schema":"unsupported","payload":"SYNTHETIC_BAD_SCHEMA","payload_sha256":"x"}\n',
            "UNSUPPORTED_KIS_RAW_SCHEMA_LINE:2",
        ),
        (
            b'{"schema":"kis-realtime-raw-v1","payload":"SYNTHETIC_BAD_HASH","payload_sha256":"x"}\n',
            "KIS_RAW_PAYLOAD_HASH_MISMATCH_LINE:2",
        ),
    ],
)
def test_full_file_reader_and_manifest_detect_interior_corruption_while_append_guard_checks_tail_only(
    tmp_path: Path, invalid_middle: bytes, expected_error: str
):
    path = tmp_path / "interior-corruption.jsonl"
    store = KISRealtimeRawStore(path)
    _append_valid_record(store, sequence=1)

    donor = KISRealtimeRawStore(tmp_path / "valid-tail.jsonl")
    _append_valid_record(donor, sequence=2)
    with path.open("ab") as handle:
        handle.write(invalid_middle)
        handle.write(donor.path.read_bytes())

    before_append = path.read_bytes()
    appended = _append_valid_record(store, sequence=3)

    assert appended["sequence"] == 3
    assert path.read_bytes() != before_append
    assert path.read_bytes().startswith(before_append)

    with pytest.raises(ValueError, match=expected_error):
        store.records()
    with pytest.raises(ValueError, match=expected_error):
        store.records(tolerate_truncated_tail=True)
    with pytest.raises(ValueError, match=expected_error):
        store.write_manifest(
            source="SYNTHETIC:DERIVED_SCENARIO",
            endpoint="SYNTHETIC:INTERIOR_CORRUPTION",
            tolerate_truncated_tail=True,
        )
    assert not path.with_suffix(path.suffix + ".manifest.json").exists()
