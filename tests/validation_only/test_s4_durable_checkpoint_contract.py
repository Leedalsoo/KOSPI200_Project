from __future__ import annotations

import json
import sqlite3

import pytest

from application.composition.validation_only_s4_checkpoint import (
    S4ExecutionEventIdentity,
    S4ExecutionStage,
    SqliteS4ValidationCheckpointStore,
    ValidationOnlyS4CheckpointCoordinator,
)

SOURCE = "SYNTHETIC:S4_CHECKPOINT_CONTRACT_V1"
ACCOUNT = "validation-account-001"
EXECUTION_SOURCE = "validation-vssf-engine-001"
RUN = "validation-run-001"
STRATEGY = "track4_gamma_scalping"
GROUP = "s4-group-001"
EXECUTION = "EXEC-000001"


def identity(*, source=SOURCE, account=ACCOUNT, execution_source=EXECUTION_SOURCE,
             execution_id=EXECUTION):
    return S4ExecutionEventIdentity(
        source_namespace=source,
        account_id=account,
        execution_source_id=execution_source,
        execution_id=execution_id,
    )


def event_payload(*, fingerprint="fill-fingerprint-001"):
    return {
        "run_id": RUN,
        "strategy_id": STRATEGY,
        "group_id": GROUP,
        "client_order_id": "client-order-001",
        "fingerprint": fingerprint,
        "status": "FILLED",
        "filled_quantity": 1,
        "remaining_quantity": 0,
        "execution_timestamp": "2026-11-27T09:00:00+09:00",
    }


def checkpoint(*, checkpoint_id, revision, previous_checkpoint_id=None,
               phase="ACCOUNT_APPLIED", balance="1000000"):
    return {
        "schema_version": 1,
        "checkpoint_id": checkpoint_id,
        "run_id": RUN,
        "strategy_id": STRATEGY,
        "group_id": GROUP,
        "source_namespace": SOURCE,
        "account_id": ACCOUNT,
        "execution_source_id": EXECUTION_SOURCE,
        "execution_id": EXECUTION,
        "revision": revision,
        "previous_checkpoint_id": previous_checkpoint_id,
        "phase": phase,
        "validation_only": True,
        "runtime_use": "PROHIBITED_OUTSIDE_VALIDATION",
        "state": {
            "account_state": {"balance": balance, "positions": []},
            "bridge_state": {"applied_execution_ids": [EXECUTION]},
            "strategy_state": {"exit_pending": False},
            "pending_orders": [],
            "position_lots": [],
            "fee_ledger": [],
            "execution_watermarks": {EXECUTION_SOURCE: EXECUTION},
            "callback_state": {"completed": phase in {"CALLBACK_APPLIED", "ACKED"}},
        },
    }


def test_execution_identity_requires_complete_validation_namespace():
    with pytest.raises(ValueError, match="S4_CHECKPOINT_EXECUTION_IDENTITY_REQUIRED"):
        S4ExecutionEventIdentity(
            source_namespace="", account_id=ACCOUNT,
            execution_source_id=EXECUTION_SOURCE, execution_id=EXECUTION,
        )
    with pytest.raises(ValueError, match="S4_CHECKPOINT_VALIDATION_NAMESPACE_REQUIRED"):
        identity(source="KIS_LIVE")


def test_receipt_is_durable_and_duplicate_identity_with_same_payload_is_idempotent(tmp_path):
    path = tmp_path / "s4-checkpoint.sqlite3"
    first = SqliteS4ValidationCheckpointStore(path)
    assert first.record_received(identity(), event_payload()) == "RECEIVED"
    assert first.record_received(identity(), event_payload()) == "RECEIVED"

    reopened = SqliteS4ValidationCheckpointStore(path)
    assert reopened.get_event_status(identity()) == "RECEIVED"
    assert len(reopened.pending_events()) == 1


def test_same_execution_id_in_different_account_or_source_namespace_is_not_collapsed(tmp_path):
    store = SqliteS4ValidationCheckpointStore(tmp_path / "s4-identities.sqlite3")
    store.record_received(identity(), event_payload())
    other_account_payload = event_payload(fingerprint="account-2-fill")
    other_account_payload["group_id"] = "s4-group-account-2"
    store.record_received(
        identity(account="validation-account-002"), other_account_payload,
    )
    other_source_payload = event_payload(fingerprint="source-2-fill")
    other_source_payload["group_id"] = "s4-group-source-2"
    store.record_received(
        identity(execution_source="validation-vssf-engine-002"), other_source_payload,
    )
    assert len(store.pending_events()) == 3


def test_same_execution_identity_with_conflicting_payload_is_quarantined(tmp_path):
    store = SqliteS4ValidationCheckpointStore(tmp_path / "s4-conflict.sqlite3")
    store.record_received(identity(), event_payload())
    with pytest.raises(ValueError, match="S4_EXECUTION_ID_PAYLOAD_CONFLICT"):
        store.record_received(identity(), event_payload(fingerprint="different-fill"))


def test_projection_stages_must_follow_account_bridge_callback_ack_order(tmp_path):
    store = SqliteS4ValidationCheckpointStore(tmp_path / "s4-stage-order.sqlite3")
    store.record_received(identity(), event_payload())
    with pytest.raises(ValueError, match="S4_CHECKPOINT_STAGE_OUT_OF_ORDER"):
        store.commit_stage(identity(), S4ExecutionStage.BRIDGE_APPLIED,
                           checkpoint(checkpoint_id="cp-1", revision=1, phase="BRIDGE_APPLIED"))


def test_checkpoint_and_stage_commit_are_atomic_and_revision_is_compare_and_swap(tmp_path):
    store = SqliteS4ValidationCheckpointStore(tmp_path / "s4-atomic.sqlite3")
    store.record_received(identity(), event_payload())
    with pytest.raises(ValueError, match="S4_CHECKPOINT_REVISION_CONFLICT"):
        store.commit_stage(identity(), S4ExecutionStage.ACCOUNT_APPLIED,
                           checkpoint(checkpoint_id="cp-bad", revision=2))
    assert store.get_event_status(identity()) == "RECEIVED"
    assert store.load_latest_checkpoint(RUN, STRATEGY, GROUP, ACCOUNT) is None

    store.commit_stage(identity(), S4ExecutionStage.ACCOUNT_APPLIED,
                       checkpoint(checkpoint_id="cp-1", revision=1))
    assert store.get_event_status(identity()) == "ACCOUNT_APPLIED"
    assert store.load_latest_checkpoint(RUN, STRATEGY, GROUP, ACCOUNT)["checkpoint_id"] == "cp-1"


def test_full_projection_ack_survives_store_recreation_and_stops_pending_replay(tmp_path):
    path = tmp_path / "s4-full-ack.sqlite3"
    store = SqliteS4ValidationCheckpointStore(path)
    event = identity()
    store.record_received(event, event_payload())
    stages = (
        (S4ExecutionStage.ACCOUNT_APPLIED, "ACCOUNT_APPLIED"),
        (S4ExecutionStage.BRIDGE_APPLIED, "BRIDGE_APPLIED"),
        (S4ExecutionStage.CALLBACK_APPLIED, "CALLBACK_APPLIED"),
        (S4ExecutionStage.ACKED, "ACKED"),
    )
    previous = None
    for revision, (stage, phase) in enumerate(stages, start=1):
        checkpoint_id = f"cp-{revision}"
        store.commit_stage(
            event, stage,
            checkpoint(checkpoint_id=checkpoint_id, revision=revision,
                       previous_checkpoint_id=previous, phase=phase),
        )
        previous = checkpoint_id

    restarted = SqliteS4ValidationCheckpointStore(path)
    assert restarted.get_event_status(event) == "ACKED"
    assert restarted.pending_events() == []
    latest = restarted.load_latest_checkpoint(RUN, STRATEGY, GROUP, ACCOUNT)
    assert latest["checkpoint_id"] == "cp-4"
    assert latest["state"]["callback_state"]["completed"] is True


def test_checkpoint_scope_and_complete_projection_state_are_required(tmp_path):
    store = SqliteS4ValidationCheckpointStore(tmp_path / "s4-scope.sqlite3")
    event = identity()
    store.record_received(event, event_payload())
    wrong = checkpoint(checkpoint_id="cp-wrong", revision=1)
    wrong["group_id"] = "other-group"
    with pytest.raises(ValueError, match="S4_CHECKPOINT_SCOPE_MISMATCH"):
        store.commit_stage(event, S4ExecutionStage.ACCOUNT_APPLIED, wrong)

    missing = checkpoint(checkpoint_id="cp-missing", revision=1)
    del missing["state"]["fee_ledger"]
    with pytest.raises(ValueError, match="S4_CHECKPOINT_STATE_INCOMPLETE"):
        store.commit_stage(event, S4ExecutionStage.ACCOUNT_APPLIED, missing)
    assert store.get_event_status(event) == "RECEIVED"


def test_checkpoint_payload_tampering_is_detected(tmp_path):
    path = tmp_path / "s4-tamper.sqlite3"
    store = SqliteS4ValidationCheckpointStore(path)
    event = identity()
    store.record_received(event, event_payload())
    store.commit_stage(event, S4ExecutionStage.ACCOUNT_APPLIED,
                       checkpoint(checkpoint_id="cp-1", revision=1))
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER s4_checkpoint_no_update")
        connection.execute("UPDATE s4_checkpoint SET payload_json='{}' WHERE checkpoint_id='cp-1'")
    with pytest.raises(ValueError, match="S4_CHECKPOINT_INTEGRITY_FAILURE"):
        SqliteS4ValidationCheckpointStore(path).load_latest_checkpoint(RUN, STRATEGY, GROUP, ACCOUNT)


def test_event_and_checkpoint_tables_reject_mutation(tmp_path):
    path = tmp_path / "s4-append-only.sqlite3"
    store = SqliteS4ValidationCheckpointStore(path)
    event = identity()
    store.record_received(event, event_payload())
    with sqlite3.connect(path) as connection, pytest.raises(
        sqlite3.IntegrityError, match="S4_CHECKPOINT_APPEND_ONLY",
    ):
        connection.execute("DELETE FROM s4_execution_event")


def test_checkpoint_replay_is_idempotent_but_conflicting_checkpoint_id_is_rejected(tmp_path):
    store = SqliteS4ValidationCheckpointStore(tmp_path / "s4-checkpoint-id.sqlite3")
    event = identity()
    store.record_received(event, event_payload())
    first = checkpoint(checkpoint_id="cp-1", revision=1)
    store.commit_stage(event, S4ExecutionStage.ACCOUNT_APPLIED, first)
    store.commit_stage(event, S4ExecutionStage.ACCOUNT_APPLIED, first)
    conflict = checkpoint(checkpoint_id="cp-1", revision=1, balance="999")
    with pytest.raises(ValueError, match="S4_CHECKPOINT_ID_CONFLICT"):
        store.commit_stage(event, S4ExecutionStage.ACCOUNT_APPLIED, conflict)

def test_callback_checkpoint_remains_pending_until_durable_ack_commit(tmp_path):
    path = tmp_path / "s4-callback-ack.sqlite3"
    store = SqliteS4ValidationCheckpointStore(path)
    event = identity()
    store.record_received(event, event_payload())
    previous = None
    for revision, stage, phase in (
        (1, S4ExecutionStage.ACCOUNT_APPLIED, "ACCOUNT_APPLIED"),
        (2, S4ExecutionStage.BRIDGE_APPLIED, "BRIDGE_APPLIED"),
        (3, S4ExecutionStage.CALLBACK_APPLIED, "CALLBACK_APPLIED"),
    ):
        checkpoint_id = f"cp-{revision}"
        store.commit_stage(
            event, stage,
            checkpoint(checkpoint_id=checkpoint_id, revision=revision,
                       previous_checkpoint_id=previous, phase=phase),
        )
        previous = checkpoint_id

    pending = SqliteS4ValidationCheckpointStore(path).pending_events()
    assert len(pending) == 1
    assert pending[0]["stage"] == "CALLBACK_APPLIED"
    assert pending[0]["next_stage"] == "ACKED"


def test_checkpoint_chain_detects_broken_previous_link(tmp_path):
    path = tmp_path / "s4-chain.sqlite3"
    store = SqliteS4ValidationCheckpointStore(path)
    event = identity()
    store.record_received(event, event_payload())
    store.commit_stage(event, S4ExecutionStage.ACCOUNT_APPLIED,
                       checkpoint(checkpoint_id="cp-1", revision=1))
    store.commit_stage(event, S4ExecutionStage.BRIDGE_APPLIED,
                       checkpoint(checkpoint_id="cp-2", revision=2,
                                  previous_checkpoint_id="cp-1", phase="BRIDGE_APPLIED"))
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER s4_checkpoint_no_update")
        payload = json.loads(connection.execute(
            "SELECT payload_json FROM s4_checkpoint WHERE checkpoint_id='cp-2'"
        ).fetchone()[0])
        payload["previous_checkpoint_id"] = "missing-checkpoint"
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        import hashlib
        connection.execute(
            "UPDATE s4_checkpoint SET previous_checkpoint_id=?, payload_json=?, payload_sha256=? WHERE checkpoint_id='cp-2'",
            ("missing-checkpoint", body, hashlib.sha256(body.encode("utf-8")).hexdigest()),
        )
    with pytest.raises(ValueError, match="S4_CHECKPOINT_CHAIN_INVALID"):
        SqliteS4ValidationCheckpointStore(path).load_latest_checkpoint(RUN, STRATEGY, GROUP, ACCOUNT)


def test_event_payload_tampering_is_detected_before_duplicate_receipt_or_replay(tmp_path):
    path = tmp_path / "s4-event-tamper.sqlite3"
    store = SqliteS4ValidationCheckpointStore(path)
    event = identity()
    store.record_received(event, event_payload())
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER s4_event_no_update")
        connection.execute(
            "UPDATE s4_execution_event SET payload_json='{}' WHERE execution_id=?", (EXECUTION,),
        )
    reopened = SqliteS4ValidationCheckpointStore(path)
    with pytest.raises(ValueError, match="S4_EXECUTION_EVENT_INTEGRITY_FAILURE"):
        reopened.record_received(event, event_payload())
    with pytest.raises(ValueError, match="S4_EXECUTION_EVENT_INTEGRITY_FAILURE"):
        reopened.pending_events()


def test_ack_cannot_skip_callback_projection_stage(tmp_path):
    store = SqliteS4ValidationCheckpointStore(tmp_path / "s4-no-skip.sqlite3")
    event = identity()
    store.record_received(event, event_payload())
    with pytest.raises(ValueError, match="S4_CHECKPOINT_STAGE_OUT_OF_ORDER"):
        store.commit_stage(event, S4ExecutionStage.ACKED,
                           checkpoint(checkpoint_id="cp-1", revision=1, phase="ACKED"))
    assert store.get_event_status(event) == "RECEIVED"

def test_single_checkpoint_coordinator_exposes_manual_recovery_without_auto_replay(tmp_path):
    from application.composition.validation_only_s4_checkpoint import (
        ValidationOnlyS4CheckpointCoordinator,
    )

    coordinator = ValidationOnlyS4CheckpointCoordinator(
        SqliteS4ValidationCheckpointStore(tmp_path / "s4-coordinator.sqlite3")
    )
    event = identity()
    assert coordinator.receive_execution(event, event_payload()) == "RECEIVED"
    coordinator.commit_projection(
        event, S4ExecutionStage.ACCOUNT_APPLIED,
        checkpoint(checkpoint_id="cp-1", revision=1),
    )

    restarted = ValidationOnlyS4CheckpointCoordinator(
        SqliteS4ValidationCheckpointStore(tmp_path / "s4-coordinator.sqlite3")
    )
    work = restarted.recovery_work()
    assert len(work) == 1
    assert work[0]["stage"] == "ACCOUNT_APPLIED"
    assert work[0]["next_stage"] == "BRIDGE_APPLIED"
    assert work[0]["last_committed_checkpoint"]["checkpoint_id"] == "cp-1"
    # Recovery is a plan only; no projection or ACK stage is invoked automatically.
    assert restarted.store.get_event_status(event) == "ACCOUNT_APPLIED"


@pytest.mark.parametrize("change, error", [
    ({"status": "UNKNOWN"}, "S4_EXECUTION_EVENT_STATUS_INVALID"),
    ({"filled_quantity": 0}, "S4_EXECUTION_EVENT_QUANTITY_INVALID"),
    ({"remaining_quantity": -1}, "S4_EXECUTION_EVENT_QUANTITY_INVALID"),
    ({"execution_timestamp": "2026-11-27T09:00:00"}, "S4_EXECUTION_EVENT_TIME_INVALID"),
    ({"client_order_id": ""}, "S4_EXECUTION_EVENT_PAYLOAD_INVALID"),
])
def test_received_execution_event_requires_fill_identity_status_quantity_and_event_time(tmp_path, change, error):
    payload = event_payload()
    payload.update(change)
    store = SqliteS4ValidationCheckpointStore(tmp_path / "s4-event-contract.sqlite3")
    with pytest.raises(ValueError, match=error):
        store.record_received(identity(), payload)
    assert store.pending_events() == []


def test_versioned_synthetic_fixture_declares_validation_only_checkpoint_contract():
    from pathlib import Path

    fixture_path = Path("tests/fixtures/track4/synthetic_s4_durable_checkpoint_contract_v1.json")
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert fixture["fixture_id"] == "S4-DURABLE-CHECKPOINT-CONTRACT-001"
    assert fixture["validation_only"] is True
    assert fixture["runtime_use"] == "PROHIBITED_OUTSIDE_VALIDATION"
    assert fixture["stages"] == [
        "RECEIVED", "ACCOUNT_APPLIED", "BRIDGE_APPLIED", "CALLBACK_APPLIED", "ACKED",
    ]
    assert fixture["execution_identity"]["execution_id"] == EXECUTION
    assert fixture["checkpoint_scope"] == ["run_id", "strategy_id", "group_id", "account_id"]
    assert fixture["single_inflight_event_scope"] == fixture["checkpoint_scope"]


def test_group_serializes_unacknowledged_events_but_allows_next_after_ack(tmp_path):
    store = SqliteS4ValidationCheckpointStore(tmp_path / "s4-group-serial.sqlite3")
    first = identity(execution_id="EXEC-000001")
    second = identity(execution_id="EXEC-000002")
    store.record_received(first, event_payload(fingerprint="fill-1"))
    with pytest.raises(ValueError, match="S4_GROUP_EVENT_IN_FLIGHT"):
        store.record_received(second, event_payload(fingerprint="fill-2"))

    previous = None
    for revision, stage, phase in (
        (1, S4ExecutionStage.ACCOUNT_APPLIED, "ACCOUNT_APPLIED"),
        (2, S4ExecutionStage.BRIDGE_APPLIED, "BRIDGE_APPLIED"),
        (3, S4ExecutionStage.CALLBACK_APPLIED, "CALLBACK_APPLIED"),
        (4, S4ExecutionStage.ACKED, "ACKED"),
    ):
        checkpoint_id = f"cp-{revision}"
        store.commit_stage(first, stage, checkpoint(
            checkpoint_id=checkpoint_id, revision=revision,
            previous_checkpoint_id=previous, phase=phase,
        ))
        previous = checkpoint_id

    assert store.record_received(second, event_payload(fingerprint="fill-2")) == "RECEIVED"


def test_different_groups_can_have_independent_inflight_events(tmp_path):
    store = SqliteS4ValidationCheckpointStore(tmp_path / "s4-group-independent.sqlite3")
    store.record_received(identity(), event_payload())
    other_group_payload = event_payload(fingerprint="other-group-fill")
    other_group_payload["group_id"] = "s4-group-002"
    assert store.record_received(
        identity(execution_id="EXEC-000002"), other_group_payload,
    ) == "RECEIVED"
    assert len(store.pending_events()) == 2


def test_execution_source_owner_cannot_change_within_a_checkpoint_lineage(tmp_path):
    store = SqliteS4ValidationCheckpointStore(tmp_path / "s4-owner-lineage.sqlite3")
    first = identity()
    store.record_received(first, event_payload())
    previous = None
    for revision, stage, phase in (
        (1, S4ExecutionStage.ACCOUNT_APPLIED, "ACCOUNT_APPLIED"),
        (2, S4ExecutionStage.BRIDGE_APPLIED, "BRIDGE_APPLIED"),
        (3, S4ExecutionStage.CALLBACK_APPLIED, "CALLBACK_APPLIED"),
        (4, S4ExecutionStage.ACKED, "ACKED"),
    ):
        checkpoint_id = f"cp-{revision}"
        store.commit_stage(first, stage, checkpoint(
            checkpoint_id=checkpoint_id, revision=revision,
            previous_checkpoint_id=previous, phase=phase,
        ))
        previous = checkpoint_id

    with pytest.raises(ValueError, match="S4_CHECKPOINT_EXECUTION_SOURCE_CHANGED"):
        store.record_received(
            identity(execution_source="new-engine-after-restart"),
            event_payload(fingerprint="new-engine-fill"),
        )


def test_os_process_termination_restores_last_committed_checkpoint_in_fresh_process(tmp_path):
    import os
    import subprocess
    import sys

    database = tmp_path / "s4-os-process-restart.sqlite3"
    child_code = r'''import sys
from pathlib import Path
from application.composition.validation_only_s4_checkpoint import (
    S4ExecutionEventIdentity, S4ExecutionStage,
    SqliteS4ValidationCheckpointStore,
    ValidationOnlyS4CheckpointCoordinator, ValidationOnlyS4CheckpointCoordinator,
)
database = Path(sys.argv[1])
identity = S4ExecutionEventIdentity(
    source_namespace="SYNTHETIC:S4_CHECKPOINT_CONTRACT_V1",
    account_id="validation-account-001",
    execution_source_id="validation-vssf-engine-001",
    execution_id="EXEC-000001",
)
payload = {
    "run_id": "validation-run-001", "strategy_id": "track4_gamma_scalping",
    "group_id": "s4-group-001", "client_order_id": "client-order-001",
    "fingerprint": "fill-fingerprint-001", "status": "FILLED",
    "filled_quantity": 1, "remaining_quantity": 0,
    "execution_timestamp": "2026-11-27T09:00:00+09:00",
}
coordinator = ValidationOnlyS4CheckpointCoordinator(SqliteS4ValidationCheckpointStore(database))
coordinator.receive_execution(identity, payload)
checkpoint = {
    "schema_version": 1, "checkpoint_id": "os-restart-cp-1",
    "run_id": payload["run_id"], "strategy_id": payload["strategy_id"],
    "group_id": payload["group_id"], "source_namespace": identity.source_namespace,
    "account_id": identity.account_id, "execution_source_id": identity.execution_source_id,
    "execution_id": identity.execution_id, "revision": 1,
    "previous_checkpoint_id": None, "phase": "ACCOUNT_APPLIED",
    "validation_only": True, "runtime_use": "PROHIBITED_OUTSIDE_VALIDATION",
    "state": {
        "account_state": {"balance": "1000000", "positions": []},
        "bridge_state": {"applied_execution_ids": []},
        "strategy_state": {"exit_pending": False}, "pending_orders": [],
        "position_lots": [], "fee_ledger": [],
        "execution_watermarks": {}, "callback_state": {"completed": False},
    },
}
coordinator.commit_projection(identity, S4ExecutionStage.ACCOUNT_APPLIED, checkpoint)
# This mutation intentionally exists only in the dying process's memory.
dirty_uncommitted_balance = "999999999"
print("CHECKPOINT_COMMITTED", flush=True)
while True:
    time.sleep(1)
'''
    child = subprocess.Popen(
        [sys.executable, "-c", child_code, str(database)],
        cwd=os.getcwd(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "CHECKPOINT_COMMITTED"
        child.terminate()
        child.wait(timeout=10)
        assert child.returncode is not None
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)

    restarted = SqliteS4ValidationCheckpointStore(database)
    event = identity()
    assert restarted.get_event_status(event) == "ACCOUNT_APPLIED"
    latest = restarted.load_latest_checkpoint(RUN, STRATEGY, GROUP, ACCOUNT)
    assert latest["checkpoint_id"] == "os-restart-cp-1"
    assert latest["state"]["account_state"]["balance"] == "1000000"
    coordinator = ValidationOnlyS4CheckpointCoordinator(restarted)
    work = coordinator.recovery_work()
    assert len(work) == 1
    assert work[0]["stage"] == "ACCOUNT_APPLIED"
    assert work[0]["next_stage"] == "BRIDGE_APPLIED"
    assert work[0]["last_committed_checkpoint"]["checkpoint_id"] == "os-restart-cp-1"
    assert restarted.get_event_status(event) == "ACCOUNT_APPLIED"


def test_cross_process_recovery_and_late_fill_redelivery_preserve_event_ack_boundary(tmp_path):
    import os
    import subprocess
    import sys

    database = tmp_path / "s4-cross-process-late-fill.sqlite3"
    first_process = r'''import sys
from pathlib import Path
from application.composition.validation_only_s4_checkpoint import (
    S4ExecutionEventIdentity, S4ExecutionStage,
    SqliteS4ValidationCheckpointStore, ValidationOnlyS4CheckpointCoordinator,
)
db = Path(sys.argv[1])
identity = S4ExecutionEventIdentity("SYNTHETIC:S4_CHECKPOINT_CONTRACT_V1", "validation-account-001", "validation-vssf-engine-001", "EXEC-000001")
payload = {"run_id":"validation-run-001", "strategy_id":"track4_gamma_scalping", "group_id":"s4-group-001", "client_order_id":"client-order-001", "fingerprint":"fill-fingerprint-001", "status":"FILLED", "filled_quantity":1, "remaining_quantity":0, "execution_timestamp":"2026-11-27T09:00:00+09:00"}
coordinator = ValidationOnlyS4CheckpointCoordinator(SqliteS4ValidationCheckpointStore(db))
coordinator.receive_execution(identity, payload)
checkpoint = {"schema_version":1,"checkpoint_id":"cross-process-cp-1","run_id":payload["run_id"],"strategy_id":payload["strategy_id"],"group_id":payload["group_id"],"source_namespace":identity.source_namespace,"account_id":identity.account_id,"execution_source_id":identity.execution_source_id,"execution_id":identity.execution_id,"revision":1,"previous_checkpoint_id":None,"phase":"ACCOUNT_APPLIED","validation_only":True,"runtime_use":"PROHIBITED_OUTSIDE_VALIDATION","state":{"account_state":{"balance":"1000000","positions":["EXEC-000001"]},"bridge_state":{"applied_execution_ids":[]},"strategy_state":{"exit_pending":False},"pending_orders":[],"position_lots":[],"fee_ledger":[],"execution_watermarks":{},"callback_state":{"completed":False}}}
coordinator.commit_projection(identity, S4ExecutionStage.ACCOUNT_APPLIED, checkpoint)
print("ACCOUNT_CHECKPOINT_COMMITTED", flush=True)
'''
    first = subprocess.run(
        [sys.executable, "-c", first_process, str(database)],
        cwd=os.getcwd(), capture_output=True, text=True, timeout=20, check=False,
    )
    assert first.returncode == 0, first.stderr
    assert "ACCOUNT_CHECKPOINT_COMMITTED" in first.stdout

    second_process = r'''import sys
from pathlib import Path
from application.composition.validation_only_s4_checkpoint import (
    S4ExecutionEventIdentity, S4ExecutionStage,
    SqliteS4ValidationCheckpointStore, ValidationOnlyS4CheckpointCoordinator,
)
db = Path(sys.argv[1])
store = SqliteS4ValidationCheckpointStore(db)
coordinator = ValidationOnlyS4CheckpointCoordinator(store)
identity = S4ExecutionEventIdentity("SYNTHETIC:S4_CHECKPOINT_CONTRACT_V1", "validation-account-001", "validation-vssf-engine-001", "EXEC-000001")
payload = {"run_id":"validation-run-001", "strategy_id":"track4_gamma_scalping", "group_id":"s4-group-001", "client_order_id":"client-order-001", "fingerprint":"fill-fingerprint-001", "status":"FILLED", "filled_quantity":1, "remaining_quantity":0, "execution_timestamp":"2026-11-27T09:00:00+09:00"}
assert coordinator.receive_execution(identity, payload) == "ACCOUNT_APPLIED"
work = coordinator.recovery_work()
assert len(work) == 1 and work[0]["next_stage"] == "BRIDGE_APPLIED"
previous = "cross-process-cp-1"
revision = 1
def commit_all(event_identity, event_payload, prefix, start_revision):
    global previous, revision
    for stage in (S4ExecutionStage.BRIDGE_APPLIED, S4ExecutionStage.CALLBACK_APPLIED, S4ExecutionStage.ACKED):
        revision += 1
        phase = stage.value
        state = {"account_state":{"balance":"1000000","positions":[event_identity.execution_id]},"bridge_state":{"applied_execution_ids":[event_identity.execution_id] if stage != S4ExecutionStage.BRIDGE_APPLIED else []},"strategy_state":{"exit_pending":False},"pending_orders":[],"position_lots":[],"fee_ledger":[],"execution_watermarks":{},"callback_state":{"completed":stage in (S4ExecutionStage.CALLBACK_APPLIED,S4ExecutionStage.ACKED)}}
        cp = {"schema_version":1,"checkpoint_id":f"{prefix}-{revision}","run_id":event_payload["run_id"],"strategy_id":event_payload["strategy_id"],"group_id":event_payload["group_id"],"source_namespace":event_identity.source_namespace,"account_id":event_identity.account_id,"execution_source_id":event_identity.execution_source_id,"execution_id":event_identity.execution_id,"revision":revision,"previous_checkpoint_id":previous,"phase":phase,"validation_only":True,"runtime_use":"PROHIBITED_OUTSIDE_VALIDATION","state":state}
        coordinator.commit_projection(event_identity, stage, cp)
        previous = cp["checkpoint_id"]
commit_all(identity, payload, "first-event", 2)
late_identity = S4ExecutionEventIdentity(identity.source_namespace, identity.account_id, identity.execution_source_id, "EXEC-000000-LATE")
late_payload = dict(payload, client_order_id="client-order-late", fingerprint="late-fill-fingerprint", execution_timestamp="2026-11-27T08:59:59+09:00")
assert coordinator.receive_execution(late_identity, late_payload) == "RECEIVED"
revision += 1
late_account = {"schema_version":1,"checkpoint_id":f"late-account-{revision}","run_id":late_payload["run_id"],"strategy_id":late_payload["strategy_id"],"group_id":late_payload["group_id"],"source_namespace":late_identity.source_namespace,"account_id":late_identity.account_id,"execution_source_id":late_identity.execution_source_id,"execution_id":late_identity.execution_id,"revision":revision,"previous_checkpoint_id":previous,"phase":"ACCOUNT_APPLIED","validation_only":True,"runtime_use":"PROHIBITED_OUTSIDE_VALIDATION","state":{"account_state":{"balance":"1000000","positions":["EXEC-000001","EXEC-000000-LATE"]},"bridge_state":{"applied_execution_ids":["EXEC-000001"]},"strategy_state":{"exit_pending":False},"pending_orders":[],"position_lots":[],"fee_ledger":[],"execution_watermarks":{},"callback_state":{"completed":False}}}
coordinator.commit_projection(late_identity, S4ExecutionStage.ACCOUNT_APPLIED, late_account)
previous = late_account["checkpoint_id"]
commit_all(late_identity, late_payload, "late-event", revision)
assert coordinator.recovery_work() == []
print("CROSS_PROCESS_RECOVERY_AND_LATE_FILL_ACKED", flush=True)
'''
    second = subprocess.run(
        [sys.executable, "-c", second_process, str(database)],
        cwd=os.getcwd(), capture_output=True, text=True, timeout=20, check=False,
    )
    assert second.returncode == 0, second.stderr
    assert "CROSS_PROCESS_RECOVERY_AND_LATE_FILL_ACKED" in second.stdout

    restarted = SqliteS4ValidationCheckpointStore(database)
    coordinator = ValidationOnlyS4CheckpointCoordinator(restarted)
    first_identity = identity()
    late_identity = identity(execution_id="EXEC-000000-LATE")
    assert coordinator.receive_execution(first_identity, event_payload()) == "ACKED"
    late_payload = dict(event_payload(fingerprint="late-fill-fingerprint"),
                        client_order_id="client-order-late",
                        execution_timestamp="2026-11-27T08:59:59+09:00")
    assert coordinator.receive_execution(late_identity, late_payload) == "ACKED"
    with pytest.raises(ValueError, match="S4_EXECUTION_ID_PAYLOAD_CONFLICT"):
        coordinator.receive_execution(late_identity, dict(late_payload, filled_quantity=2))
    assert coordinator.recovery_work() == []
    latest = restarted.load_latest_checkpoint(RUN, STRATEGY, GROUP, ACCOUNT)
    assert latest["revision"] == 8
    assert latest["phase"] == "ACKED"
    assert latest["state"]["callback_state"]["completed"] is True


def test_two_recovery_processes_can_observe_same_unclaimed_work_before_stage_cas(tmp_path):
    """Characterize duplicate dispatch before durable stage compare-and-swap."""
    import os
    import subprocess
    import sys
    import time

    database = tmp_path / "s4-concurrent-recovery.sqlite3"
    store = SqliteS4ValidationCheckpointStore(database)
    event = identity()
    store.record_received(event, event_payload())
    store.commit_stage(
        event,
        S4ExecutionStage.ACCOUNT_APPLIED,
        checkpoint(checkpoint_id="cp-1", revision=1),
    )

    worker = r'''
import sys, time
from pathlib import Path
from application.composition.validation_only_s4_checkpoint import (
    S4ExecutionEventIdentity, S4ExecutionStage,
    SqliteS4ValidationCheckpointStore, ValidationOnlyS4CheckpointCoordinator,
)
database, worker_id, directory = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
store = SqliteS4ValidationCheckpointStore(database)
coordinator = ValidationOnlyS4CheckpointCoordinator(store)
work = coordinator.recovery_work()
assert len(work) == 1
item = work[0]
assert item["stage"] == "ACCOUNT_APPLIED" and item["next_stage"] == "BRIDGE_APPLIED"
assert item["last_committed_checkpoint"]["checkpoint_id"] == "cp-1"
(directory / (worker_id + ".ready")).write_text(item["identity"]["execution_id"], encoding="utf-8")
deadline = time.monotonic() + 20
while not (directory / "release").exists():
    if time.monotonic() > deadline:
        raise TimeoutError("release barrier timeout")
    time.sleep(0.01)
# Synthetic callback side effect occurs before the durable stage CAS.
with (directory / "callbacks.log").open("a", encoding="utf-8") as stream:
    stream.write(worker_id + "\n")
identity = S4ExecutionEventIdentity(**item["identity"])
checkpoint = {
    "schema_version": 1,
    "checkpoint_id": "cp-2-" + worker_id,
    "run_id": "validation-run-001",
    "strategy_id": "track4_gamma_scalping",
    "group_id": "s4-group-001",
    "source_namespace": "SYNTHETIC:S4_CHECKPOINT_CONTRACT_V1",
    "account_id": "validation-account-001",
    "execution_source_id": "validation-vssf-engine-001",
    "execution_id": "EXEC-000001",
    "revision": 2,
    "previous_checkpoint_id": "cp-1",
    "phase": "BRIDGE_APPLIED",
    "validation_only": True,
    "runtime_use": "PROHIBITED_OUTSIDE_VALIDATION",
    "state": {
        "account_state": {"balance": "1000000", "positions": []},
        "bridge_state": {"applied_execution_ids": ["EXEC-000001"]},
        "strategy_state": {"exit_pending": False},
        "pending_orders": [],
        "position_lots": [],
        "fee_ledger": [],
        "execution_watermarks": {"validation-vssf-engine-001": "EXEC-000001"},
        "callback_state": {"completed": False},
    },
}
try:
    coordinator.commit_projection(identity, S4ExecutionStage.BRIDGE_APPLIED, checkpoint)
    result = "COMMITTED"
except ValueError as error:
    result = str(error)
(directory / (worker_id + ".result")).write_text(result, encoding="utf-8")
'''
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", worker, str(database), worker_id, str(tmp_path)],
            cwd=os.getcwd(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        for worker_id in ("worker-a", "worker-b")
    ]
    try:
        deadline = time.monotonic() + 20
        while not all((tmp_path / (name + ".ready")).exists() for name in ("worker-a", "worker-b")):
            if time.monotonic() > deadline:
                raise TimeoutError("workers did not both observe pending recovery work")
            if any(process.poll() not in (None, 0) for process in processes):
                raise AssertionError("worker exited before barrier")
            time.sleep(0.01)
        (tmp_path / "release").write_text("go", encoding="utf-8")
        outputs = [process.communicate(timeout=30) for process in processes]
        assert all(process.returncode == 0 for process in processes), outputs
    finally:
        (tmp_path / "release").write_text("go", encoding="utf-8")
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

    callback_calls = (tmp_path / "callbacks.log").read_text(encoding="utf-8").splitlines()
    results = [(tmp_path / (name + ".result")).read_text(encoding="utf-8")
               for name in ("worker-a", "worker-b")]
    assert len(callback_calls) == 2
    assert sorted(results) == ["COMMITTED", "S4_CHECKPOINT_STAGE_CONFLICT"]
    assert store.get_event_status(event) == "BRIDGE_APPLIED"
    assert len(store.pending_events()) == 1
    assert store.pending_events()[0]["next_stage"] == "CALLBACK_APPLIED"
