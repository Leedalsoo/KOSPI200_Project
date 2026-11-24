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


def test_concurrent_writer_interleaving_between_tail_validation_and_append_can_damage_raw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "writer-interleaving.jsonl"
    store = KISRealtimeRawStore(path)
    _append_valid_record(store, sequence=1)
    original_validate = store._validate_append_tail
    interleaved = False

    def validate_then_interleave() -> None:
        nonlocal interleaved
        original_validate()
        if not interleaved:
            interleaved = True
            # Deterministic stand-in for another writer leaving a partial row
            # after this writer validates the tail but before it opens append.
            with path.open("ab") as competing_writer:
                competing_writer.write(
                    b'{"schema":"kis-realtime-raw-v1","payload":"SYNTHETIC_CONCURRENT_PARTIAL'
                )

    monkeypatch.setattr(store, "_validate_append_tail", validate_then_interleave)
    appended = _append_valid_record(store, sequence=2)

    assert appended["sequence"] == 2
    raw = path.read_bytes()
    assert b"SYNTHETIC_CONCURRENT_PARTIAL" in raw
    assert b"SYNTHETIC:DERIVED_SCENARIO:TRACK4-VALID" in raw
    with pytest.raises(ValueError, match="INVALID_KIS_RAW_RECORD_LINE:2"):
        store.records()


@pytest.mark.parametrize("collector_count", [2])
def test_independent_collectors_sharing_raw_path_can_persist_duplicate_local_sequences(
    tmp_path: Path, collector_count: int
):
    async def run() -> None:
        path = tmp_path / "shared-raw.jsonl"
        store_a = KISRealtimeRawStore(path)
        store_b = KISRealtimeRawStore(path)

        class FrameTransport:
            def __init__(self, payload: str) -> None:
                self.payload = payload

            async def connect(self) -> None:
                return None

            async def subscribe(self, tr_id: str, symbol: str) -> None:
                return None

            async def recv(self) -> str:
                return self.payload

            async def close(self) -> None:
                return None

        payloads = [
            "0|H0IOCNT0|1|SYNTHETIC:DERIVED_SCENARIO:COLLECTOR-A",
            "0|H0IOCNT0|1|SYNTHETIC:DERIVED_SCENARIO:COLLECTOR-B",
        ]
        collectors = [
            KISRealtimeCollector(
                FrameTransport(payloads[0]), store_a, clock=lambda: NOW
            ),
            KISRealtimeCollector(
                FrameTransport(payloads[1]), store_b, clock=lambda: NOW
            ),
        ]
        assert len(collectors) == collector_count

        for collector in collectors:
            await collector.start("20261124", SUBSCRIPTIONS)
        returned = [await collector.capture_one() for collector in collectors]
        persisted = KISRealtimeRawStore(path).records()

        assert [record["sequence"] for record in returned] == [1, 1]
        assert [record["sequence"] for record in persisted] == [1, 1]
        assert [record["payload"] for record in persisted] == payloads
        assert len({record["payload_sha256"] for record in persisted}) == 2

    asyncio.run(run())


def test_frame_observer_runs_after_raw_record_is_readable(tmp_path: Path):
    async def run() -> None:
        path = tmp_path / "observer-order.jsonl"
        store = KISRealtimeRawStore(path)
        payloads = [
            "0|H0IOCNT0|1|SYNTHETIC:DERIVED_SCENARIO:OBSERVER-ORDER-A",
            "0|H0IOCNT0|2|SYNTHETIC:DERIVED_SCENARIO:OBSERVER-ORDER-B",
        ]
        observed: list[tuple[str, datetime, int]] = []

        class QueueTransport:
            def __init__(self) -> None:
                self.index = 0

            async def connect(self) -> None:
                return None

            async def subscribe(self, tr_id: str, symbol: str) -> None:
                return None

            async def recv(self) -> str:
                payload = payloads[self.index]
                self.index += 1
                return payload

            async def close(self) -> None:
                return None

        def observer(payload: str, received_at: datetime) -> None:
            records_visible_at_callback = store.records()
            assert records_visible_at_callback[-1]["payload"] == payload
            assert (
                records_visible_at_callback[-1]["received_at"]
                == received_at.isoformat()
            )
            observed.append((payload, received_at, len(records_visible_at_callback)))

        collector = KISRealtimeCollector(
            QueueTransport(), store, clock=lambda: NOW, frame_observer=observer
        )
        await collector.start("20261124", SUBSCRIPTIONS)
        first = await collector.capture_one()
        second = await collector.capture_one()

        assert [item[2] for item in observed] == [1, 2]
        assert [item[0] for item in observed] == payloads
        assert [first["sequence"], second["sequence"]] == [1, 2]
        assert len(store.records()) == 2

    asyncio.run(run())


def test_observer_failure_does_not_automatically_replay_before_next_capture(
    tmp_path: Path,
):
    async def run() -> None:
        store = KISRealtimeRawStore(tmp_path / "observer-continuation.jsonl")
        payloads = [
            "0|H0IOCNT0|1|SYNTHETIC:DERIVED_SCENARIO:OBSERVER-FAIL-FIRST",
            "0|H0IOCNT0|2|SYNTHETIC:DERIVED_SCENARIO:OBSERVER-NEXT-FRAME",
        ]
        observer_calls: list[str] = []
        partial_effects: list[str] = []

        class QueueTransport:
            def __init__(self) -> None:
                self.index = 0

            async def connect(self) -> None:
                return None

            async def subscribe(self, tr_id: str, symbol: str) -> None:
                return None

            async def recv(self) -> str:
                payload = payloads[self.index]
                self.index += 1
                return payload

            async def close(self) -> None:
                return None

        def observer(payload: str, received_at: datetime) -> None:
            observer_calls.append(payload)
            partial_effects.append(payload)
            if payload == payloads[0]:
                raise RuntimeError("SYNTHETIC_OBSERVER_FAILURE_AFTER_PARTIAL_EFFECT")

        collector = KISRealtimeCollector(
            QueueTransport(), store, clock=lambda: NOW, frame_observer=observer
        )
        await collector.start("20261124", SUBSCRIPTIONS)

        try:
            await collector.capture_one()
        except RuntimeError as exc:
            assert str(exc) == "SYNTHETIC_OBSERVER_FAILURE_AFTER_PARTIAL_EFFECT"
        else:
            raise AssertionError("observer exception must propagate")

        after_failure = store.records()
        assert [record["payload"] for record in after_failure] == [payloads[0]]
        assert [record["sequence"] for record in after_failure] == [1]
        assert observer_calls == [payloads[0]]
        assert partial_effects == [payloads[0]]

        second = await collector.capture_one()
        final_records = store.records()
        assert second["payload"] == payloads[1]
        assert [record["payload"] for record in final_records] == payloads
        assert [record["sequence"] for record in final_records] == [1, 2]
        assert observer_calls == payloads
        assert partial_effects == payloads

    asyncio.run(run())


def test_two_same_process_writers_append_after_shared_empty_tail_validation(
    tmp_path: Path,
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    path = tmp_path / "simultaneous-writers.jsonl"
    stores = [KISRealtimeRawStore(path), KISRealtimeRawStore(path)]
    validation_barrier = Barrier(2)
    payloads = [
        "0|H0IOCNT0|1|SYNTHETIC:DERIVED_SCENARIO:WRITER-A",
        "0|H0IOCNT0|1|SYNTHETIC:DERIVED_SCENARIO:WRITER-B",
    ]

    def append_after_validation(store: KISRealtimeRawStore, payload: str) -> dict:
        original_validate = store._validate_append_tail

        def validate_then_wait() -> None:
            original_validate()
            validation_barrier.wait(timeout=5)

        store._validate_append_tail = validate_then_wait  # type: ignore[method-assign]
        return store.append(
            received_at=NOW,
            trading_date="20261124",
            instrument="SYNTHETIC:DERIVED_SCENARIO:SHARED-RAW",
            tr_id="H0IOCNT0",
            payload=payload,
            sequence=1,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        returned = list(
            executor.map(
                lambda item: append_after_validation(*item),
                zip(stores, payloads),
            )
        )

    persisted = KISRealtimeRawStore(path).records()
    assert {record["payload"] for record in returned} == set(payloads)
    persisted_payloads = {record["payload"] for record in persisted}
    assert persisted_payloads <= set(payloads)
    assert 1 <= len(persisted) <= 2
    assert [record["sequence"] for record in persisted] == [1] * len(persisted)
