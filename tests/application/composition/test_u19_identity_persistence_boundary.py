from datetime import datetime, timezone
from decimal import Decimal

from contracts.types import BrokerOrderCommand, OptionInstrumentIdentity
from core.oms.oms_fsm import OrderStateMachine
from core.oms.track2_u19_recovery import (
    U19ExecutionEvent,
    U19Position,
    U19RecoveryDecision,
    U19RecoveryStatus,
)
from environments.live.settlement.sqlite_settlement_store import SQLiteSettlementStore
from environments.virtual.position.track2_u19_recovery_store import SqliteTrack2U19RecoveryStore


def _identity():
    return OptionInstrumentIdentity(
        instrument_id="SYNTHETIC_CONTRACT:U19:CALL:20261112:500",
        symbol="SYNTHETIC_CONTRACT:U19:CALL:20261112:500",
        expiry="20261112", option_type="CALL", strike=Decimal("500"),
        contract_multiplier=Decimal("250000"),
        identity_source="SYNTHETIC:DERIVED_SCENARIO",
    )


def test_oms_sqlite_restart_restores_full_option_identity_fields(tmp_path):
    store = SQLiteSettlementStore(tmp_path / "oms-identity.sqlite3")
    identity = _identity()
    command = BrokerOrderCommand(
        client_order_id="U19-IDENTITY-ORDER",
        instrument_id=identity.instrument_id,
        side="BUY", quantity=2, order_type="LIMIT",
        broker_symbol=identity.symbol, instrument_identity=identity,
        asset_type="OPTION", requested_price=Decimal("12.5"),
        strategy_id="U19_SYNTHETIC", order_purpose="VALIDATION_ONLY",
        track_id="U19_SYNTHETIC", tag_id="CALL-500", group_id="U19-GROUP",
        leg_id="CALL-500",
    )
    oms = OrderStateMachine(persistence_store=store)
    oms.apply_intent(command)
    oms.register_broker_order_command(command)

    raw = store.load_order_state_payloads()[0]["broker_order_command"]["instrument_identity"]
    assert raw["kind"] == "option"
    assert raw["fields"] == {
        "instrument_id": identity.instrument_id,
        "symbol": identity.symbol,
        "expiry": identity.expiry,
        "option_type": identity.option_type,
        "strike": "500",
        "contract_multiplier": "250000",
        "identity_source": "SYNTHETIC:DERIVED_SCENARIO",
    }

    restarted = OrderStateMachine(persistence_store=SQLiteSettlementStore(store.path))
    restarted.restore_from_store()
    restored = restarted.get(command.client_order_id).broker_order_command.instrument_identity
    assert restored == identity
    assert restored.contract_multiplier == Decimal("250000")
    assert restored.identity_source == "SYNTHETIC:DERIVED_SCENARIO"


def test_u19_checkpoint_keeps_position_quantity_contract_separate_from_instrument_master(tmp_path):
    identity = _identity()
    position = U19Position(identity.instrument_id, Decimal("2"))
    decision = U19RecoveryDecision(
        checkpoint_id="U19-CHECKPOINT-IDENTITY-BOUNDARY",
        group_id="U19-GROUP",
        status=U19RecoveryStatus.RESTORE_ALLOWED,
        reason="VALIDATION_ONLY_SYNTHETIC_MATCH",
        as_of=datetime(2026, 11, 20, 0, 0, tzinfo=timezone.utc),
        position_basis="BROKER_AND_LEDGER",
        positions=(position,),
        broker_snapshot_sha256="a" * 64,
        ledger_snapshot_sha256="b" * 64,
        broker_snapshot_id="BROKER-SNAPSHOT-1",
        ledger_snapshot_id="LEDGER-SNAPSHOT-1",
        broker_positions=(position,),
        ledger_positions=(position,),
        execution_events=(U19ExecutionEvent("EXEC-U19-1", "c" * 64),),
        pending_order_ids=(),
        expected_group_manifest_id="EXPECTED-GROUP-1",
        expected_group_manifest_sha256="d" * 64,
        restore_allowed=True,
        strategy_resume_allowed=True,
    )
    store = SqliteTrack2U19RecoveryStore(tmp_path / "u19-checkpoint.sqlite3")
    store.save(decision.to_checkpoint())
    restored = store.load_latest("U19-GROUP")

    assert restored["positions"] == [
        {"instrument_id": identity.instrument_id, "signed_quantity": "2"}
    ]
    assert "contract_multiplier" not in restored["positions"][0]
    assert "identity_source" not in restored["positions"][0]
    assert restored["execution_events"] == [
        {"execution_id": "EXEC-U19-1", "fingerprint": "c" * 64}
    ]
    assert restored["order_submission_enabled"] is False
    assert restored["new_entry_enabled"] is False
