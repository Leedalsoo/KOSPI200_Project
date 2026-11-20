import json

import pytest

from environments.high_speed.track6_validation_state_store import (
    Track6ValidationStateStore,
    Track6ValidationStateStoreError,
)


def test_track6_validation_state_store_appends_and_restores_latest_snapshot(tmp_path):
    store = Track6ValidationStateStore(tmp_path, run_id="S6-RUN-1")
    first = {"run_id": "S6-RUN-1", "status": "ORDER_WORKING", "open_quantity": {"put": 0, "call": 0}}
    second = {"run_id": "S6-RUN-1", "status": "SINGLE_LEG_FILLED", "open_quantity": {"put": 1, "call": 0}}

    first_hash = store.append(first)
    second_hash = store.append(second)

    latest = store.load_latest()
    assert latest["sequence"] == 2
    assert latest["record_sha256"] == second_hash
    assert latest["snapshot"] == second
    assert first_hash != second_hash
    assert len(store.path.read_text(encoding="utf-8").splitlines()) == 2


def test_track6_validation_state_store_rejects_run_id_mismatch(tmp_path):
    store = Track6ValidationStateStore(tmp_path, run_id="S6-RUN-1")
    with pytest.raises(Track6ValidationStateStoreError, match="RUN_ID_MISMATCH"):
        store.append({"run_id": "S6-RUN-2"})


def test_track6_validation_state_store_rejects_tampered_record(tmp_path):
    store = Track6ValidationStateStore(tmp_path, run_id="S6-RUN-1")
    store.append({"run_id": "S6-RUN-1", "status": "ORDER_WORKING"})
    lines = store.path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["snapshot"]["status"] = "PAIR_ACTIVE"
    store.path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    with pytest.raises(Track6ValidationStateStoreError, match="HASH_MISMATCH"):
        store.load_latest()


def test_track6_validation_state_store_rejects_torn_tail(tmp_path):
    store = Track6ValidationStateStore(tmp_path, run_id="S6-RUN-1")
    store.append({"run_id": "S6-RUN-1", "status": "ORDER_WORKING"})
    with store.path.open("a", encoding="utf-8") as stream:
        stream.write('{"partial":')
    with pytest.raises(Track6ValidationStateStoreError, match="TORN_RECORD"):
        store.load_latest()


def test_track6_validation_state_store_rejects_path_traversal(tmp_path):
    with pytest.raises(ValueError, match="RUN_ID_INVALID"):
        Track6ValidationStateStore(tmp_path, run_id="../outside")


def test_track6_validation_state_store_rejects_broken_previous_hash_chain(tmp_path):
    store = Track6ValidationStateStore(tmp_path, run_id="S6-RUN-CHAIN")
    store.append({"run_id": "S6-RUN-CHAIN", "status": "FIRST"})
    store.append({"run_id": "S6-RUN-CHAIN", "status": "SECOND"})
    lines = store.path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    record["previous_record_sha256"] = "0" * 64
    lines[1] = json.dumps(record)
    store.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(Track6ValidationStateStoreError, match="CHAIN_INVALID"):
        Track6ValidationStateStore(tmp_path, run_id="S6-RUN-CHAIN").load_latest()


def test_track6_validation_state_store_rejects_sequence_gap(tmp_path):
    store = Track6ValidationStateStore(tmp_path, run_id="S6-RUN-SEQ")
    store.append({"run_id": "S6-RUN-SEQ", "status": "FIRST"})
    lines = store.path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["sequence"] = 2
    body = {key: value for key, value in record.items() if key != "record_sha256"}
    record["record_sha256"] = __import__("hashlib").sha256(Track6ValidationStateStore._canonical(body)).hexdigest()
    store.path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    with pytest.raises(Track6ValidationStateStoreError, match="SEQUENCE_INVALID"):
        Track6ValidationStateStore(tmp_path, run_id="S6-RUN-SEQ").load_latest()


def test_track6_validation_state_store_revalidates_cached_stream_before_append(tmp_path):
    store = Track6ValidationStateStore(tmp_path, run_id="S6-RUN-CACHED")
    store.append({"run_id": "S6-RUN-CACHED", "status": "ORIGINAL"})
    lines = store.path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["snapshot"]["status"] = "TAMPERED"
    store.path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    with pytest.raises(Track6ValidationStateStoreError, match="HASH_MISMATCH"):
        store.append({"run_id": "S6-RUN-CACHED", "status": "SHOULD_NOT_APPEND"})
    assert len(store.path.read_text(encoding="utf-8").splitlines()) == 1


def test_track6_validation_state_store_recovers_after_fsync_failure(tmp_path, monkeypatch):
    import environments.high_speed.track6_validation_state_store as state_store_module

    store = Track6ValidationStateStore(tmp_path, run_id="S6-RUN-FSYNC")
    snapshot = {"run_id": "S6-RUN-FSYNC", "status": "DURABILITY_UNCERTAIN"}

    def fail_fsync(_fd):
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(state_store_module.os, "fsync", fail_fsync)
    with pytest.raises(OSError, match="simulated fsync failure"):
        store.append(snapshot)

    # The write may already be visible even though durability confirmation failed.
    # A fresh instance must validate the persisted chain before appending again.
    monkeypatch.undo()
    restored = Track6ValidationStateStore(tmp_path, run_id="S6-RUN-FSYNC")
    latest = restored.load_latest()
    assert latest["sequence"] == 1
    assert latest["snapshot"] == snapshot
    restored.append({"run_id": "S6-RUN-FSYNC", "status": "AFTER_RESTART"})
    assert restored.load_latest()["sequence"] == 2


def test_track6_validation_state_store_rejects_short_write_and_keeps_torn_tail_fail_closed(tmp_path, monkeypatch):
    import environments.high_speed.track6_validation_state_store as state_store_module

    store = Track6ValidationStateStore(tmp_path, run_id="S6-RUN-SHORT")
    real_fdopen = state_store_module.os.fdopen

    class ShortWriteStream:
        def __init__(self, raw):
            self.raw = raw

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.raw.close()

        def write(self, payload):
            return self.raw.write(payload[: max(1, len(payload) // 2)])

        def flush(self):
            self.raw.flush()

        def fileno(self):
            return self.raw.fileno()

    monkeypatch.setattr(
        state_store_module.os,
        "fdopen",
        lambda fd, mode, closefd=True: ShortWriteStream(real_fdopen(fd, mode, closefd=closefd)),
    )
    with pytest.raises(Track6ValidationStateStoreError, match="WRITE_INCOMPLETE"):
        store.append({"run_id": "S6-RUN-SHORT", "status": "PARTIAL"})

    monkeypatch.undo()
    restarted = Track6ValidationStateStore(tmp_path, run_id="S6-RUN-SHORT")
    with pytest.raises(Track6ValidationStateStoreError, match="TORN_RECORD"):
        restarted.load_latest()
    with pytest.raises(Track6ValidationStateStoreError, match="TORN_RECORD"):
        restarted.append({"run_id": "S6-RUN-SHORT", "status": "MUST_NOT_APPEND"})
