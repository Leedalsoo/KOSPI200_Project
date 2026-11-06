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
