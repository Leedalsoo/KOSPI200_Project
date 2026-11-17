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

def test_s2_four_leg_runtime_state_is_captured_and_reconciled_after_u19_restart(tmp_path, monkeypatch):
    from environments.virtual.position.virtual_position_lot_store import VirtualPositionLotStore

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
    original_apply_execution = VirtualPositionLotStore.apply_execution

    def capture_attach(*args, **kwargs):
        loop = original_attach(*args, **kwargs)
        captured["loop"] = loop
        return loop

    def capture_four_open_lots(store, lot):
        original_apply_execution(store, lot)
        open_lots = tuple(store.open_lots())
        if len(open_lots) == 4 and "lots" not in captured:
            account = (
                captured["loop"].multi_leg_bridge.bundle.execution
                ._authoritative_execute.__self__.vssf_runtime.account
            )
            captured["lots"] = open_lots
            captured["account_positions"] = {
                instrument_id: int(position["qty"]) * (1 if str(position["side"]).upper() == "BUY" else -1)
                for instrument_id, position in account.positions.items()
            }

    monkeypatch.setattr(replay, "attach_standard_automated_loop", capture_attach)
    monkeypatch.setattr(VirtualPositionLotStore, "apply_execution", capture_four_open_lots)

    binding = bind_validation_only_track2_quote_scenario_profile(
        source_manifest_path=SIDECAR / "manifest.json",
        source_profile_path=SOURCE_PROFILE,
        target_profile_path=VALIDATION_PROFILE,
        output_dir=tmp_path / "u19-four-leg-bound-sidecar",
        purpose="U19_FOUR_LEG_RUNTIME_RESTART_VALIDATION_ONLY",
    )
    trace_path = tmp_path / "s2-u19-four-leg-runtime-trace.jsonl"
    report = replay.HighSpeedVirtualRuntimeReplayRunner(
        DATASET,
        run_id="Q25-A8-R9-S2-U19-FOUR-LEG-RESTART-86-20261118",
        strategy_keys=(("track2_asymmetric_trap", "1.0"),),
        validation_only_synthetic=True,
        validation_only_track2_manifest=DATASET / "manifest.json",
        validation_only_track2_risk_profile=VALIDATION_PROFILE,
        validation_only_track2_quote_scenario_manifest=binding.manifest_path,
        log_mode="detailed",
        trace_output=trace_path,
    ).run(max_events=86)

    assert report.events == 86
    assert report.signals == 2
    assert report.filled == 8
    assert report.rejected == 0
    assert len(captured["lots"]) == 4
    assert len(captured["account_positions"]) == 4
    lots = captured["lots"]
    group_ids = {lot.group_id for lot in lots}
    assert len(group_ids) == 1
    assert {lot.remaining_quantity for lot in lots} == {1}

    lot_positions = tuple(sorted(
        (
            U19Position(
                instrument_id=lot.instrument_id,
                signed_quantity=Decimal(str(
                    lot.remaining_quantity if lot.side == "BUY" else -lot.remaining_quantity
                )),
            )
            for lot in lots
        ),
        key=lambda item: item.instrument_id,
    ))
    account_positions = tuple(sorted(
        (
            U19Position(instrument_id, Decimal(str(quantity)))
            for instrument_id, quantity in captured["account_positions"].items()
        ),
        key=lambda item: item.instrument_id,
    ))
    assert account_positions == lot_positions

    trace = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    fills_by_id = {
        item["payload"]["execution_id"]: item["payload"]
        for item in trace
        if item.get("event_type") == "fill"
    }
    execution_events = tuple(
        U19ExecutionEvent(lot.execution_id, _digest(fills_by_id[lot.execution_id]))
        for lot in lots
    )
    assert len(execution_events) == 4
    as_of = max(lot.execution_timestamp for lot in lots)
    group_id = next(iter(group_ids))
    broker_payload = {
        "group_id": group_id,
        "positions": [(item.instrument_id, str(item.signed_quantity)) for item in account_positions],
    }
    ledger_payload = {
        "group_id": group_id,
        "positions": [(item.instrument_id, str(item.signed_quantity)) for item in lot_positions],
        "execution_events": [
            (item.execution_id, item.fingerprint) for item in execution_events
        ],
    }
    broker_snapshot = U19BrokerPositionSnapshot(
        group_id=group_id,
        snapshot_id="validation-vssf-four-leg-account-snapshot",
        as_of=as_of,
        source="VALIDATION_ONLY:BROKER_EXCHANGE",
        positions=account_positions,
        complete=True,
        capability_verified=True,
        payload_sha256=_digest(broker_payload),
    )
    ledger_snapshot = U19ExecutionLedgerSnapshot(
        group_id=group_id,
        snapshot_id="validation-four-leg-positionlot-ledger",
        as_of=as_of,
        source="VALIDATION_ONLY:EXECUTION_LEDGER",
        positions=lot_positions,
        complete=True,
        payload_sha256=_digest(ledger_payload),
        execution_events=execution_events,
        pending_order_ids=(),
    )

    checkpoint_path = tmp_path / "u19-four-leg-runtime-restart.sqlite3"
    decision = ValidationOnlyTrack2U19RecoveryCoordinator(
        SqliteTrack2U19RecoveryStore(checkpoint_path)
    ).recover(
        group_id=group_id,
        broker_snapshot=broker_snapshot,
        ledger_snapshot=ledger_snapshot,
    )
    assert decision.status is U19RecoveryStatus.RESTORE_ALLOWED
    assert decision.positions == account_positions
    assert decision.execution_events == execution_events
    assert decision.new_entry_enabled is False
    assert decision.order_submission_enabled is False
    assert decision.runtime_restore_performed is False

    restarted_store = SqliteTrack2U19RecoveryStore(checkpoint_path)
    persisted = restarted_store.load_latest(group_id)
    assert persisted is not None
    assert persisted["status"] == U19RecoveryStatus.RESTORE_ALLOWED.value
    assert len(persisted["positions"]) == 4
    assert persisted["broker_positions"] == persisted["ledger_positions"]
    assert len(persisted["execution_events"]) == 4
    assert persisted["new_entry_enabled"] is False
    assert persisted["order_submission_enabled"] is False
    assert persisted["runtime_restore_performed"] is False
