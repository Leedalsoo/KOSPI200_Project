from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

import environments.high_speed.virtual_runtime_replay as replay
from application.composition.track2_u19_recovery import ValidationOnlyTrack2U19RecoveryCoordinator
from core.oms.track2_u19_recovery import (
    U19BrokerPositionSnapshot,
    U19ExecutionEvent,
    U19ExecutionLedgerSnapshot,
    U19Position,
    U19RecoveryStatus,
)
from environments.virtual.position.track2_u19_recovery_store import SqliteTrack2U19RecoveryStore
from verification.track2_quote_profile_binding import bind_validation_only_track2_quote_scenario_profile


ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "data/accepted_market_data/runtime_v2"
SIDECAR = ROOT / "data/derived_scenario/q25_a8_p2_recovered_track2_four_leg_quotes_v3_market_calibrated_r3_20261115"
SOURCE_PROFILE = ROOT / "config/validation_only/track2/synthetic_scenario_profile.market_calibrated.v2.json"
VALIDATION_PROFILE = ROOT / "config/validation_only/track2/synthetic_scenario_profile.exit_path_test.v3.json"


def _digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(payload).hexdigest()


def test_s2_runtime_position_lot_reconciles_and_survives_u19_checkpoint_restart(tmp_path, monkeypatch):
    required = (
        DATASET / "manifest.json",
        DATASET / "20261012.jsonl",
        DATASET / "20261013.jsonl",
        SIDECAR / "manifest.json",
        SIDECAR / "four_leg_quotes.jsonl",
        SIDECAR / "candidate_inputs.json",
        SOURCE_PROFILE,
        VALIDATION_PROFILE,
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        pytest.skip(
            "No.1534 reuse-first inputs are not materialized in this checkout; compare preserved source inventory "
            f"before treating them as absent: {missing}"
        )

    captured = {}
    original_attach = replay.attach_standard_automated_loop

    def capture_attach(*args, **kwargs):
        loop = original_attach(*args, **kwargs)
        captured["loop"] = loop
        return loop

    monkeypatch.setattr(replay, "attach_standard_automated_loop", capture_attach)
    binding = bind_validation_only_track2_quote_scenario_profile(
        source_manifest_path=SIDECAR / "manifest.json",
        source_profile_path=SOURCE_PROFILE,
        target_profile_path=VALIDATION_PROFILE,
        output_dir=tmp_path / "u19-bound-sidecar",
        purpose="U19_RESTART_POSITIONLOT_RECONCILIATION_VALIDATION_ONLY",
    )
    trace_path = tmp_path / "s2-u19-runtime-trace.jsonl"
    report = replay.HighSpeedVirtualRuntimeReplayRunner(
        DATASET,
        run_id="Q25-A8-R9-S2-U19-RUNTIME-RESTART-85-20261117",
        strategy_keys=(("track2_asymmetric_trap", "1.0"),),
        validation_only_synthetic=True,
        validation_only_track2_manifest=DATASET / "manifest.json",
        validation_only_track2_risk_profile=VALIDATION_PROFILE,
        validation_only_track2_quote_scenario_manifest=binding.manifest_path,
        log_mode="detailed",
        trace_output=trace_path,
    ).run(max_events=85)

    loop = captured["loop"]
    bridge = loop.multi_leg_bridge
    open_lots = tuple(bridge.position_lot_store.open_lots())
    account_positions = bridge.bundle.execution._authoritative_execute.__self__.vssf_runtime.account.positions
    trace = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    fills = [item for item in trace if item.get("event_type") == "fill"]

    assert report.events == 85
    assert report.signals == 1
    assert report.filled == 1
    assert report.rejected == 0
    assert len(open_lots) == 1
    assert len(account_positions) == 1
    lot = open_lots[0]
    assert lot.remaining_quantity == 1
    assert lot.group_id
    assert lot.execution_id == fills[0]["payload"]["execution_id"]

    runtime_position = U19Position(
        instrument_id=lot.instrument_id,
        signed_quantity=Decimal(str(lot.remaining_quantity if lot.side == "BUY" else -lot.remaining_quantity)),
    )
    as_of = datetime.fromisoformat(fills[0]["payload"]["execution_timestamp"])
    execution_event = U19ExecutionEvent(
        execution_id=lot.execution_id,
        fingerprint=_digest(fills[0]["payload"]),
    )
    broker_payload = {"group_id": lot.group_id, "positions": [(runtime_position.instrument_id, str(runtime_position.signed_quantity))]}
    ledger_payload = {"group_id": lot.group_id, "positions": [(runtime_position.instrument_id, str(runtime_position.signed_quantity))], "execution_id": lot.execution_id}
    broker_snapshot = U19BrokerPositionSnapshot(
        group_id=lot.group_id,
        snapshot_id="validation-vssf-account-snapshot-1",
        as_of=as_of,
        source="VALIDATION_ONLY:BROKER_EXCHANGE",
        positions=(runtime_position,),
        complete=True,
        capability_verified=True,
        payload_sha256=_digest(broker_payload),
    )
    ledger_snapshot = U19ExecutionLedgerSnapshot(
        group_id=lot.group_id,
        snapshot_id="validation-positionlot-execution-ledger-1",
        as_of=as_of,
        source="VALIDATION_ONLY:EXECUTION_LEDGER",
        positions=(runtime_position,),
        complete=True,
        payload_sha256=_digest(ledger_payload),
        execution_events=(execution_event,),
        pending_order_ids=(),
    )

    checkpoint_path = tmp_path / "u19-runtime-restart.sqlite3"
    first = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(checkpoint_path)
    ).recover(group_id=lot.group_id, broker_snapshot=broker_snapshot, ledger_snapshot=ledger_snapshot)
    assert first.status is U19RecoveryStatus.RESTORE_ALLOWED
    assert first.position_basis == "BROKER_EXCHANGE"
    assert first.positions == (runtime_position,)
    assert first.new_entry_enabled is False
    assert first.order_submission_enabled is False
    assert first.runtime_restore_performed is False

    restarted_store = SqliteTrack2U19RecoveryStore(checkpoint_path)
    persisted = restarted_store.load_latest(lot.group_id)
    assert persisted is not None
    assert persisted["status"] == U19RecoveryStatus.RESTORE_ALLOWED.value
    assert persisted["broker_positions"] == persisted["ledger_positions"]
    assert persisted["broker_positions"] == [
        {"instrument_id": lot.instrument_id, "signed_quantity": "1"}
    ]
    assert persisted["execution_events"] == [
        {"execution_id": lot.execution_id, "fingerprint": execution_event.fingerprint}
    ]

    # Reopening the checkpoint proves durable evidence persistence only; it does not restore a live Runtime.
    assert restarted_store.load_latest(lot.group_id)["order_submission_enabled"] is False
